import os, re
from datetime import datetime
import itertools

import ctypes, platform, functools, queue
from tinygrad.device import Compiler
from tinygrad.runtime.support.hcq import HCQCompiled, HCQSignal
from tinygrad.runtime.ops_cpu import CPUAllocator, CPUProgram, CPUComputeQueue, CPUWorker
from tinygrad.helpers import OSX, getenv, capstone_flatdump, DEBUG
from tinygrad.renderer.llvmir import LLVMRenderer
import tinygrad.runtime.autogen.llvm as llvm
from tinygrad.runtime.support.elf import jit_loader

def cerr(): return ctypes.pointer(ctypes.pointer(ctypes.c_char()))

def expect(x, err, ret=None):
  if x: raise RuntimeError(llvm.string_cast(err.contents) if not isinstance(err, str) else err)
  return ret

class LLVMCompiler(Compiler):
  jit = True
  target_arch = {'arm64': 'AArch64', 'aarch64': 'AArch64', 'x86_64': 'X86', 'AMD64': 'X86'}[platform.machine()]
  def __init__(self, processor:str, feats:str):
    for component in ['Target', 'TargetInfo', 'TargetMC', 'AsmParser', 'AsmPrinter']: getattr(llvm, f'LLVMInitialize{self.target_arch}{component}')()

    triple = {'AArch64': b'aarch64-none-unknown-elf', 'X86': b'x86_64-none-unknown-elf', 'AMDGPU': b'amdgcn-amd-amdhsa'}[self.target_arch]
    target = expect(llvm.LLVMGetTargetFromTriple(triple, ctypes.pointer(tgt:=llvm.LLVMTargetRef()), err:=cerr()), err, tgt)
    if DEBUG >= 3: print(f"LLVM init for {processor!r} with {feats!r}")
    self.target_machine = llvm.LLVMCreateTargetMachine(target, triple, processor.encode(), feats.encode(),
                                                       llvm.LLVMCodeGenLevelDefault, llvm.LLVMRelocPIC, llvm.LLVMCodeModelDefault)

    self.pbo = llvm.LLVMCreatePassBuilderOptions()
    if (opt:=bool(getenv("LLVMOPT", "1"))):
      self.passes = b'default<O2>'
      llvm.LLVMPassBuilderOptionsSetLoopUnrolling(self.pbo, True)
      llvm.LLVMPassBuilderOptionsSetLoopVectorization(self.pbo, True)
      llvm.LLVMPassBuilderOptionsSetSLPVectorization(self.pbo, True)
      llvm.LLVMPassBuilderOptionsSetVerifyEach(self.pbo, True)
    else:
      self.passes = b'default<O0>'

    self.diag_msgs: list[str] = []
    @ctypes.CFUNCTYPE(None, llvm.LLVMDiagnosticInfoRef, ctypes.c_void_p)
    def handle_diag(diag_ref, _arg):
      severity = llvm.LLVMGetDiagInfoSeverity(diag_ref)
      msg = ctypes.string_at(llvm.LLVMGetDiagInfoDescription(diag_ref)).decode()
      if severity == llvm.LLVMDSError:
        self.diag_msgs.append(msg)
    self.handle_diag = handle_diag
    llvm.LLVMContextSetDiagnosticHandler(llvm.LLVMGetGlobalContext(), handle_diag, None)
    super().__init__(f"compile_llvm_{self.target_arch}{'_jit' if self.jit else ''}{'_opt' if opt else ''}")

  def __del__(self): llvm.LLVMDisposePassBuilderOptions(self.pbo)



  @staticmethod
  def _scan_array_ptrs(ir_text: str) -> dict[str, int]:
      arrmap: dict[str, int] = {}
      for m in re.finditer(r'\[\s*(\d+)\s*x\s*float\s*\]\s*\*\s*%([A-Za-z0-9_\.]+)', ir_text):
          n, name = int(m.group(1)), m.group(2)
          arrmap[name] = n
      for m in re.finditer(r'%([A-Za-z0-9_\.]+)\s*=\s*alloca\s*\[\s*(\d+)\s*x\s*float\s*\]', ir_text):
          name, n = m.group(1), int(m.group(2))
          arrmap[name] = n
      for m in re.finditer(r'bitcast\s*\[\s*(\d+)\s*x\s*float\s*\]\s*\*\s*%([A-Za-z0-9_\.]+)\s*to', ir_text):
          n, name = int(m.group(1)), m.group(2)
          arrmap[name] = n
      return arrmap

  @staticmethod
  def _rewrite_ir_for_ptr_mismatch(src: str) -> str:
      arrmap = LLVMCompiler._scan_array_ptrs(src)

      # --- 1) load/store 의 벡터 포인터 미스매치: 별도 SSA bitcast 주입 ---
      # load 패턴:  "%res = load <N x float>, <N x float>* %ptr"
      load_pat = re.compile(r'''
          ^(?P<indent>\s*)
          (?P<lhs>%[A-Za-z0-9_\.]+\s*=\s*load\s*)
          (?P<vty><\s*\d+\s+x\s+float\s*>)\s*,\s*
          (?P=vty)\s*\*\s*
          (?P<ptr>%[A-Za-z0-9_\.]+)
          \s*$
      ''', re.VERBOSE)

      # store 패턴: "store <N x float> %val, <N x float>* %ptr"
      store_pat = re.compile(r'''
          ^(?P<indent>\s*)
          store\s+
          (?P<vty><\s*\d+\s+x\s+float\s*>)\s+
          (?P<val>%[A-Za-z0-9_\.]+|\{[^}]*\}|undef|zeroinitializer)\s*,\s*
          (?P=vty)\s*\*\s*
          (?P<ptr>%[A-Za-z0-9_\.]+)
          \s*$
      ''', re.VERBOSE)

      cast_id = itertools.count()

      def fix_vec_load(line: str) -> str:
          m = load_pat.match(line)
          if not m: return line
          indent, lhs, vty, ptr = m.group('indent', 'lhs', 'vty', 'ptr')
          tmp = f"%__vec_cast_{next(cast_id)}"
          cast = f"{indent}{tmp} = bitcast float* {ptr} to {vty}*"
          new  = f"{indent}{lhs}{vty}, {vty}* {tmp}"
          return cast + "\n" + new

      def fix_vec_store(line: str) -> str:
          m = store_pat.match(line)
          if not m: return line
          indent, vty, val, ptr = m.group('indent', 'vty', 'val', 'ptr')
          tmp = f"%__vec_cast_{next(cast_id)}"
          cast = f"{indent}{tmp} = bitcast float* {ptr} to {vty}*"
          new  = f"{indent}store {vty} {val}, {vty}* {tmp}"
          return cast + "\n" + new

      lines = src.splitlines()
      # 먼저 load/store 벡터 포인터만 처리
      for i, ln in enumerate(lines):
          if ' load ' in ln and '<' in ln and 'float>*' in ln:
              lines[i] = fix_vec_load(ln)
          elif ln.lstrip().startswith('store ') and '<' in ln and 'float>*' in ln:
              lines[i] = fix_vec_store(ln)
      src = "\n".join(lines)

      # --- 2) 배열 포인터 GEP는 기존대로 배열 GEP로 교체 (이미 구현하신 _fix_gep_line 사용) ---
      def _fix_gep_line(line: str) -> str:
          m = re.search(r'\bgetelementptr\b[^\n]*\bfloat\s*,\s*float\s*\*\s*(%[A-Za-z0-9_\.]+)\s*,\s*i32\s+(-?\d+)', line)
          if not m: return line
          base, idx = m.group(1), m.group(2)
          name = base[1:]
          n = arrmap.get(name)
          if not n: return line
          line = re.sub(
              r'\bgetelementptr\b[^\n]*',
              lambda mm: re.sub(
                  r'float\s*,\s*float\s*\*\s*%[A-Za-z0-9_\.]+\s*,\s*i32\s+-?\d+',
                  f'[{n} x float], [{n} x float]* {base}, i32 0, i32 {idx}',
                  mm.group(0), count=1
              ),
              line, count=1
          )
          return line

      lines = src.splitlines()
      for i, ln in enumerate(lines):
          if 'getelementptr' in ln and 'float* %' in ln:
              lines[i] = _fix_gep_line(ln)
      src = "\n".join(lines)

      return src


  def compile(self, src:str) -> bytes:
    self.diag_msgs.clear()

    # --- [A] 파싱 전 원본 IR 저장 --------------------------------------------
    if int(os.getenv("TINY_LLVM_DUMP", "0")):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            with open(f"/tmp/tinygrad_ir_{ts}_before.ll", "wb") as f:
                f.write(src.encode())
        except Exception:
            pass
    # ------------------------------------------------------------------------
    # 🔧 리라이터: 타입 불일치 핫픽스
    if int(os.getenv("TINY_LLVM_REWRITE", "1")):
        src = LLVMCompiler._rewrite_ir_for_ptr_mismatch(src)

    src_buf = llvm.LLVMCreateMemoryBufferWithMemoryRangeCopy(ctypes.create_string_buffer(src_bytes:=src.encode()), len(src_bytes), b'src')
    mod = expect(llvm.LLVMParseIRInContext(llvm.LLVMGetGlobalContext(), src_buf, ctypes.pointer(m:=llvm.LLVMModuleRef()), err:=cerr()), err, m)
    expect(llvm.LLVMVerifyModule(mod, llvm.LLVMReturnStatusAction, err:=cerr()), err)
    expect(llvm.LLVMRunPasses(mod, self.passes, self.target_machine, self.pbo), 'failed to run passes')

    # --- [B] 패스 적용 후(IR 최적화 결과) 저장 ---------------------------------
    if int(os.getenv("TINY_LLVM_DUMP", "0")):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            ir_after = ctypes.string_at(llvm.LLVMPrintModuleToString(mod)).decode()
            with open(f"/tmp/tinygrad_ir_{ts}_after.ll", "w") as f:
                f.write(ir_after)
        except Exception:
            pass
    # ------------------------------------------------------------------------


    if DEBUG >= 7: print(ctypes.string_at(llvm.LLVMPrintModuleToString(mod)).decode())
    obj_buf = expect(llvm.LLVMTargetMachineEmitToMemoryBuffer(self.target_machine, mod, llvm.LLVMObjectFile, err:=cerr(),
                                                              ctypes.pointer(buf:=llvm.LLVMMemoryBufferRef())), err, buf)
    llvm.LLVMDisposeModule(mod)
    obj = ctypes.string_at(llvm.LLVMGetBufferStart(obj_buf), llvm.LLVMGetBufferSize(obj_buf))
    llvm.LLVMDisposeMemoryBuffer(obj_buf)
    if self.diag_msgs: raise RuntimeError("llvm diagnostic: " + "\n".join(self.diag_msgs))
    return jit_loader(obj) if self.jit else obj

  def disassemble(self, lib:bytes): capstone_flatdump(lib)

class HostLLVMCompiler(LLVMCompiler):
  def __init__(self):
    # +reserve-x18 here does the same thing as -ffixed-x18 in ops_cpu.py, see comments there for why it's needed on arm osx
    cpu, feats = ctypes.string_at(llvm.LLVMGetHostCPUName()), (b'+reserve-x18,' if OSX else b'') + ctypes.string_at(llvm.LLVMGetHostCPUFeatures())
    super().__init__(cpu.decode(), feats.decode())

class LLVMDevice(HCQCompiled):
  def __init__(self, device:str=""):
    self.tasks:queue.Queue = queue.Queue()
    CPUWorker(self).start()
    super().__init__(device, CPUAllocator(self), LLVMRenderer(), HostLLVMCompiler(), functools.partial(CPUProgram, self), HCQSignal, CPUComputeQueue)
