#include "pose.h"

namespace {
#define DIM 18
#define EDIM 18
#define MEDIM 18
typedef void (*Hfun)(double *, double *, double *);
const static double MAHA_THRESH_4 = 7.814727903251177;
const static double MAHA_THRESH_10 = 7.814727903251177;
const static double MAHA_THRESH_13 = 7.814727903251177;
const static double MAHA_THRESH_14 = 7.814727903251177;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_1103084970822345352) {
   out_1103084970822345352[0] = delta_x[0] + nom_x[0];
   out_1103084970822345352[1] = delta_x[1] + nom_x[1];
   out_1103084970822345352[2] = delta_x[2] + nom_x[2];
   out_1103084970822345352[3] = delta_x[3] + nom_x[3];
   out_1103084970822345352[4] = delta_x[4] + nom_x[4];
   out_1103084970822345352[5] = delta_x[5] + nom_x[5];
   out_1103084970822345352[6] = delta_x[6] + nom_x[6];
   out_1103084970822345352[7] = delta_x[7] + nom_x[7];
   out_1103084970822345352[8] = delta_x[8] + nom_x[8];
   out_1103084970822345352[9] = delta_x[9] + nom_x[9];
   out_1103084970822345352[10] = delta_x[10] + nom_x[10];
   out_1103084970822345352[11] = delta_x[11] + nom_x[11];
   out_1103084970822345352[12] = delta_x[12] + nom_x[12];
   out_1103084970822345352[13] = delta_x[13] + nom_x[13];
   out_1103084970822345352[14] = delta_x[14] + nom_x[14];
   out_1103084970822345352[15] = delta_x[15] + nom_x[15];
   out_1103084970822345352[16] = delta_x[16] + nom_x[16];
   out_1103084970822345352[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_5459115001706413123) {
   out_5459115001706413123[0] = -nom_x[0] + true_x[0];
   out_5459115001706413123[1] = -nom_x[1] + true_x[1];
   out_5459115001706413123[2] = -nom_x[2] + true_x[2];
   out_5459115001706413123[3] = -nom_x[3] + true_x[3];
   out_5459115001706413123[4] = -nom_x[4] + true_x[4];
   out_5459115001706413123[5] = -nom_x[5] + true_x[5];
   out_5459115001706413123[6] = -nom_x[6] + true_x[6];
   out_5459115001706413123[7] = -nom_x[7] + true_x[7];
   out_5459115001706413123[8] = -nom_x[8] + true_x[8];
   out_5459115001706413123[9] = -nom_x[9] + true_x[9];
   out_5459115001706413123[10] = -nom_x[10] + true_x[10];
   out_5459115001706413123[11] = -nom_x[11] + true_x[11];
   out_5459115001706413123[12] = -nom_x[12] + true_x[12];
   out_5459115001706413123[13] = -nom_x[13] + true_x[13];
   out_5459115001706413123[14] = -nom_x[14] + true_x[14];
   out_5459115001706413123[15] = -nom_x[15] + true_x[15];
   out_5459115001706413123[16] = -nom_x[16] + true_x[16];
   out_5459115001706413123[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_7351235428474932421) {
   out_7351235428474932421[0] = 1.0;
   out_7351235428474932421[1] = 0.0;
   out_7351235428474932421[2] = 0.0;
   out_7351235428474932421[3] = 0.0;
   out_7351235428474932421[4] = 0.0;
   out_7351235428474932421[5] = 0.0;
   out_7351235428474932421[6] = 0.0;
   out_7351235428474932421[7] = 0.0;
   out_7351235428474932421[8] = 0.0;
   out_7351235428474932421[9] = 0.0;
   out_7351235428474932421[10] = 0.0;
   out_7351235428474932421[11] = 0.0;
   out_7351235428474932421[12] = 0.0;
   out_7351235428474932421[13] = 0.0;
   out_7351235428474932421[14] = 0.0;
   out_7351235428474932421[15] = 0.0;
   out_7351235428474932421[16] = 0.0;
   out_7351235428474932421[17] = 0.0;
   out_7351235428474932421[18] = 0.0;
   out_7351235428474932421[19] = 1.0;
   out_7351235428474932421[20] = 0.0;
   out_7351235428474932421[21] = 0.0;
   out_7351235428474932421[22] = 0.0;
   out_7351235428474932421[23] = 0.0;
   out_7351235428474932421[24] = 0.0;
   out_7351235428474932421[25] = 0.0;
   out_7351235428474932421[26] = 0.0;
   out_7351235428474932421[27] = 0.0;
   out_7351235428474932421[28] = 0.0;
   out_7351235428474932421[29] = 0.0;
   out_7351235428474932421[30] = 0.0;
   out_7351235428474932421[31] = 0.0;
   out_7351235428474932421[32] = 0.0;
   out_7351235428474932421[33] = 0.0;
   out_7351235428474932421[34] = 0.0;
   out_7351235428474932421[35] = 0.0;
   out_7351235428474932421[36] = 0.0;
   out_7351235428474932421[37] = 0.0;
   out_7351235428474932421[38] = 1.0;
   out_7351235428474932421[39] = 0.0;
   out_7351235428474932421[40] = 0.0;
   out_7351235428474932421[41] = 0.0;
   out_7351235428474932421[42] = 0.0;
   out_7351235428474932421[43] = 0.0;
   out_7351235428474932421[44] = 0.0;
   out_7351235428474932421[45] = 0.0;
   out_7351235428474932421[46] = 0.0;
   out_7351235428474932421[47] = 0.0;
   out_7351235428474932421[48] = 0.0;
   out_7351235428474932421[49] = 0.0;
   out_7351235428474932421[50] = 0.0;
   out_7351235428474932421[51] = 0.0;
   out_7351235428474932421[52] = 0.0;
   out_7351235428474932421[53] = 0.0;
   out_7351235428474932421[54] = 0.0;
   out_7351235428474932421[55] = 0.0;
   out_7351235428474932421[56] = 0.0;
   out_7351235428474932421[57] = 1.0;
   out_7351235428474932421[58] = 0.0;
   out_7351235428474932421[59] = 0.0;
   out_7351235428474932421[60] = 0.0;
   out_7351235428474932421[61] = 0.0;
   out_7351235428474932421[62] = 0.0;
   out_7351235428474932421[63] = 0.0;
   out_7351235428474932421[64] = 0.0;
   out_7351235428474932421[65] = 0.0;
   out_7351235428474932421[66] = 0.0;
   out_7351235428474932421[67] = 0.0;
   out_7351235428474932421[68] = 0.0;
   out_7351235428474932421[69] = 0.0;
   out_7351235428474932421[70] = 0.0;
   out_7351235428474932421[71] = 0.0;
   out_7351235428474932421[72] = 0.0;
   out_7351235428474932421[73] = 0.0;
   out_7351235428474932421[74] = 0.0;
   out_7351235428474932421[75] = 0.0;
   out_7351235428474932421[76] = 1.0;
   out_7351235428474932421[77] = 0.0;
   out_7351235428474932421[78] = 0.0;
   out_7351235428474932421[79] = 0.0;
   out_7351235428474932421[80] = 0.0;
   out_7351235428474932421[81] = 0.0;
   out_7351235428474932421[82] = 0.0;
   out_7351235428474932421[83] = 0.0;
   out_7351235428474932421[84] = 0.0;
   out_7351235428474932421[85] = 0.0;
   out_7351235428474932421[86] = 0.0;
   out_7351235428474932421[87] = 0.0;
   out_7351235428474932421[88] = 0.0;
   out_7351235428474932421[89] = 0.0;
   out_7351235428474932421[90] = 0.0;
   out_7351235428474932421[91] = 0.0;
   out_7351235428474932421[92] = 0.0;
   out_7351235428474932421[93] = 0.0;
   out_7351235428474932421[94] = 0.0;
   out_7351235428474932421[95] = 1.0;
   out_7351235428474932421[96] = 0.0;
   out_7351235428474932421[97] = 0.0;
   out_7351235428474932421[98] = 0.0;
   out_7351235428474932421[99] = 0.0;
   out_7351235428474932421[100] = 0.0;
   out_7351235428474932421[101] = 0.0;
   out_7351235428474932421[102] = 0.0;
   out_7351235428474932421[103] = 0.0;
   out_7351235428474932421[104] = 0.0;
   out_7351235428474932421[105] = 0.0;
   out_7351235428474932421[106] = 0.0;
   out_7351235428474932421[107] = 0.0;
   out_7351235428474932421[108] = 0.0;
   out_7351235428474932421[109] = 0.0;
   out_7351235428474932421[110] = 0.0;
   out_7351235428474932421[111] = 0.0;
   out_7351235428474932421[112] = 0.0;
   out_7351235428474932421[113] = 0.0;
   out_7351235428474932421[114] = 1.0;
   out_7351235428474932421[115] = 0.0;
   out_7351235428474932421[116] = 0.0;
   out_7351235428474932421[117] = 0.0;
   out_7351235428474932421[118] = 0.0;
   out_7351235428474932421[119] = 0.0;
   out_7351235428474932421[120] = 0.0;
   out_7351235428474932421[121] = 0.0;
   out_7351235428474932421[122] = 0.0;
   out_7351235428474932421[123] = 0.0;
   out_7351235428474932421[124] = 0.0;
   out_7351235428474932421[125] = 0.0;
   out_7351235428474932421[126] = 0.0;
   out_7351235428474932421[127] = 0.0;
   out_7351235428474932421[128] = 0.0;
   out_7351235428474932421[129] = 0.0;
   out_7351235428474932421[130] = 0.0;
   out_7351235428474932421[131] = 0.0;
   out_7351235428474932421[132] = 0.0;
   out_7351235428474932421[133] = 1.0;
   out_7351235428474932421[134] = 0.0;
   out_7351235428474932421[135] = 0.0;
   out_7351235428474932421[136] = 0.0;
   out_7351235428474932421[137] = 0.0;
   out_7351235428474932421[138] = 0.0;
   out_7351235428474932421[139] = 0.0;
   out_7351235428474932421[140] = 0.0;
   out_7351235428474932421[141] = 0.0;
   out_7351235428474932421[142] = 0.0;
   out_7351235428474932421[143] = 0.0;
   out_7351235428474932421[144] = 0.0;
   out_7351235428474932421[145] = 0.0;
   out_7351235428474932421[146] = 0.0;
   out_7351235428474932421[147] = 0.0;
   out_7351235428474932421[148] = 0.0;
   out_7351235428474932421[149] = 0.0;
   out_7351235428474932421[150] = 0.0;
   out_7351235428474932421[151] = 0.0;
   out_7351235428474932421[152] = 1.0;
   out_7351235428474932421[153] = 0.0;
   out_7351235428474932421[154] = 0.0;
   out_7351235428474932421[155] = 0.0;
   out_7351235428474932421[156] = 0.0;
   out_7351235428474932421[157] = 0.0;
   out_7351235428474932421[158] = 0.0;
   out_7351235428474932421[159] = 0.0;
   out_7351235428474932421[160] = 0.0;
   out_7351235428474932421[161] = 0.0;
   out_7351235428474932421[162] = 0.0;
   out_7351235428474932421[163] = 0.0;
   out_7351235428474932421[164] = 0.0;
   out_7351235428474932421[165] = 0.0;
   out_7351235428474932421[166] = 0.0;
   out_7351235428474932421[167] = 0.0;
   out_7351235428474932421[168] = 0.0;
   out_7351235428474932421[169] = 0.0;
   out_7351235428474932421[170] = 0.0;
   out_7351235428474932421[171] = 1.0;
   out_7351235428474932421[172] = 0.0;
   out_7351235428474932421[173] = 0.0;
   out_7351235428474932421[174] = 0.0;
   out_7351235428474932421[175] = 0.0;
   out_7351235428474932421[176] = 0.0;
   out_7351235428474932421[177] = 0.0;
   out_7351235428474932421[178] = 0.0;
   out_7351235428474932421[179] = 0.0;
   out_7351235428474932421[180] = 0.0;
   out_7351235428474932421[181] = 0.0;
   out_7351235428474932421[182] = 0.0;
   out_7351235428474932421[183] = 0.0;
   out_7351235428474932421[184] = 0.0;
   out_7351235428474932421[185] = 0.0;
   out_7351235428474932421[186] = 0.0;
   out_7351235428474932421[187] = 0.0;
   out_7351235428474932421[188] = 0.0;
   out_7351235428474932421[189] = 0.0;
   out_7351235428474932421[190] = 1.0;
   out_7351235428474932421[191] = 0.0;
   out_7351235428474932421[192] = 0.0;
   out_7351235428474932421[193] = 0.0;
   out_7351235428474932421[194] = 0.0;
   out_7351235428474932421[195] = 0.0;
   out_7351235428474932421[196] = 0.0;
   out_7351235428474932421[197] = 0.0;
   out_7351235428474932421[198] = 0.0;
   out_7351235428474932421[199] = 0.0;
   out_7351235428474932421[200] = 0.0;
   out_7351235428474932421[201] = 0.0;
   out_7351235428474932421[202] = 0.0;
   out_7351235428474932421[203] = 0.0;
   out_7351235428474932421[204] = 0.0;
   out_7351235428474932421[205] = 0.0;
   out_7351235428474932421[206] = 0.0;
   out_7351235428474932421[207] = 0.0;
   out_7351235428474932421[208] = 0.0;
   out_7351235428474932421[209] = 1.0;
   out_7351235428474932421[210] = 0.0;
   out_7351235428474932421[211] = 0.0;
   out_7351235428474932421[212] = 0.0;
   out_7351235428474932421[213] = 0.0;
   out_7351235428474932421[214] = 0.0;
   out_7351235428474932421[215] = 0.0;
   out_7351235428474932421[216] = 0.0;
   out_7351235428474932421[217] = 0.0;
   out_7351235428474932421[218] = 0.0;
   out_7351235428474932421[219] = 0.0;
   out_7351235428474932421[220] = 0.0;
   out_7351235428474932421[221] = 0.0;
   out_7351235428474932421[222] = 0.0;
   out_7351235428474932421[223] = 0.0;
   out_7351235428474932421[224] = 0.0;
   out_7351235428474932421[225] = 0.0;
   out_7351235428474932421[226] = 0.0;
   out_7351235428474932421[227] = 0.0;
   out_7351235428474932421[228] = 1.0;
   out_7351235428474932421[229] = 0.0;
   out_7351235428474932421[230] = 0.0;
   out_7351235428474932421[231] = 0.0;
   out_7351235428474932421[232] = 0.0;
   out_7351235428474932421[233] = 0.0;
   out_7351235428474932421[234] = 0.0;
   out_7351235428474932421[235] = 0.0;
   out_7351235428474932421[236] = 0.0;
   out_7351235428474932421[237] = 0.0;
   out_7351235428474932421[238] = 0.0;
   out_7351235428474932421[239] = 0.0;
   out_7351235428474932421[240] = 0.0;
   out_7351235428474932421[241] = 0.0;
   out_7351235428474932421[242] = 0.0;
   out_7351235428474932421[243] = 0.0;
   out_7351235428474932421[244] = 0.0;
   out_7351235428474932421[245] = 0.0;
   out_7351235428474932421[246] = 0.0;
   out_7351235428474932421[247] = 1.0;
   out_7351235428474932421[248] = 0.0;
   out_7351235428474932421[249] = 0.0;
   out_7351235428474932421[250] = 0.0;
   out_7351235428474932421[251] = 0.0;
   out_7351235428474932421[252] = 0.0;
   out_7351235428474932421[253] = 0.0;
   out_7351235428474932421[254] = 0.0;
   out_7351235428474932421[255] = 0.0;
   out_7351235428474932421[256] = 0.0;
   out_7351235428474932421[257] = 0.0;
   out_7351235428474932421[258] = 0.0;
   out_7351235428474932421[259] = 0.0;
   out_7351235428474932421[260] = 0.0;
   out_7351235428474932421[261] = 0.0;
   out_7351235428474932421[262] = 0.0;
   out_7351235428474932421[263] = 0.0;
   out_7351235428474932421[264] = 0.0;
   out_7351235428474932421[265] = 0.0;
   out_7351235428474932421[266] = 1.0;
   out_7351235428474932421[267] = 0.0;
   out_7351235428474932421[268] = 0.0;
   out_7351235428474932421[269] = 0.0;
   out_7351235428474932421[270] = 0.0;
   out_7351235428474932421[271] = 0.0;
   out_7351235428474932421[272] = 0.0;
   out_7351235428474932421[273] = 0.0;
   out_7351235428474932421[274] = 0.0;
   out_7351235428474932421[275] = 0.0;
   out_7351235428474932421[276] = 0.0;
   out_7351235428474932421[277] = 0.0;
   out_7351235428474932421[278] = 0.0;
   out_7351235428474932421[279] = 0.0;
   out_7351235428474932421[280] = 0.0;
   out_7351235428474932421[281] = 0.0;
   out_7351235428474932421[282] = 0.0;
   out_7351235428474932421[283] = 0.0;
   out_7351235428474932421[284] = 0.0;
   out_7351235428474932421[285] = 1.0;
   out_7351235428474932421[286] = 0.0;
   out_7351235428474932421[287] = 0.0;
   out_7351235428474932421[288] = 0.0;
   out_7351235428474932421[289] = 0.0;
   out_7351235428474932421[290] = 0.0;
   out_7351235428474932421[291] = 0.0;
   out_7351235428474932421[292] = 0.0;
   out_7351235428474932421[293] = 0.0;
   out_7351235428474932421[294] = 0.0;
   out_7351235428474932421[295] = 0.0;
   out_7351235428474932421[296] = 0.0;
   out_7351235428474932421[297] = 0.0;
   out_7351235428474932421[298] = 0.0;
   out_7351235428474932421[299] = 0.0;
   out_7351235428474932421[300] = 0.0;
   out_7351235428474932421[301] = 0.0;
   out_7351235428474932421[302] = 0.0;
   out_7351235428474932421[303] = 0.0;
   out_7351235428474932421[304] = 1.0;
   out_7351235428474932421[305] = 0.0;
   out_7351235428474932421[306] = 0.0;
   out_7351235428474932421[307] = 0.0;
   out_7351235428474932421[308] = 0.0;
   out_7351235428474932421[309] = 0.0;
   out_7351235428474932421[310] = 0.0;
   out_7351235428474932421[311] = 0.0;
   out_7351235428474932421[312] = 0.0;
   out_7351235428474932421[313] = 0.0;
   out_7351235428474932421[314] = 0.0;
   out_7351235428474932421[315] = 0.0;
   out_7351235428474932421[316] = 0.0;
   out_7351235428474932421[317] = 0.0;
   out_7351235428474932421[318] = 0.0;
   out_7351235428474932421[319] = 0.0;
   out_7351235428474932421[320] = 0.0;
   out_7351235428474932421[321] = 0.0;
   out_7351235428474932421[322] = 0.0;
   out_7351235428474932421[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_5276878112375474914) {
   out_5276878112375474914[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_5276878112375474914[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_5276878112375474914[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_5276878112375474914[3] = dt*state[12] + state[3];
   out_5276878112375474914[4] = dt*state[13] + state[4];
   out_5276878112375474914[5] = dt*state[14] + state[5];
   out_5276878112375474914[6] = state[6];
   out_5276878112375474914[7] = state[7];
   out_5276878112375474914[8] = state[8];
   out_5276878112375474914[9] = state[9];
   out_5276878112375474914[10] = state[10];
   out_5276878112375474914[11] = state[11];
   out_5276878112375474914[12] = state[12];
   out_5276878112375474914[13] = state[13];
   out_5276878112375474914[14] = state[14];
   out_5276878112375474914[15] = state[15];
   out_5276878112375474914[16] = state[16];
   out_5276878112375474914[17] = state[17];
}
void F_fun(double *state, double dt, double *out_8717321888493851934) {
   out_8717321888493851934[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8717321888493851934[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8717321888493851934[2] = 0;
   out_8717321888493851934[3] = 0;
   out_8717321888493851934[4] = 0;
   out_8717321888493851934[5] = 0;
   out_8717321888493851934[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8717321888493851934[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8717321888493851934[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8717321888493851934[9] = 0;
   out_8717321888493851934[10] = 0;
   out_8717321888493851934[11] = 0;
   out_8717321888493851934[12] = 0;
   out_8717321888493851934[13] = 0;
   out_8717321888493851934[14] = 0;
   out_8717321888493851934[15] = 0;
   out_8717321888493851934[16] = 0;
   out_8717321888493851934[17] = 0;
   out_8717321888493851934[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8717321888493851934[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8717321888493851934[20] = 0;
   out_8717321888493851934[21] = 0;
   out_8717321888493851934[22] = 0;
   out_8717321888493851934[23] = 0;
   out_8717321888493851934[24] = 0;
   out_8717321888493851934[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8717321888493851934[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8717321888493851934[27] = 0;
   out_8717321888493851934[28] = 0;
   out_8717321888493851934[29] = 0;
   out_8717321888493851934[30] = 0;
   out_8717321888493851934[31] = 0;
   out_8717321888493851934[32] = 0;
   out_8717321888493851934[33] = 0;
   out_8717321888493851934[34] = 0;
   out_8717321888493851934[35] = 0;
   out_8717321888493851934[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8717321888493851934[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8717321888493851934[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8717321888493851934[39] = 0;
   out_8717321888493851934[40] = 0;
   out_8717321888493851934[41] = 0;
   out_8717321888493851934[42] = 0;
   out_8717321888493851934[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8717321888493851934[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8717321888493851934[45] = 0;
   out_8717321888493851934[46] = 0;
   out_8717321888493851934[47] = 0;
   out_8717321888493851934[48] = 0;
   out_8717321888493851934[49] = 0;
   out_8717321888493851934[50] = 0;
   out_8717321888493851934[51] = 0;
   out_8717321888493851934[52] = 0;
   out_8717321888493851934[53] = 0;
   out_8717321888493851934[54] = 0;
   out_8717321888493851934[55] = 0;
   out_8717321888493851934[56] = 0;
   out_8717321888493851934[57] = 1;
   out_8717321888493851934[58] = 0;
   out_8717321888493851934[59] = 0;
   out_8717321888493851934[60] = 0;
   out_8717321888493851934[61] = 0;
   out_8717321888493851934[62] = 0;
   out_8717321888493851934[63] = 0;
   out_8717321888493851934[64] = 0;
   out_8717321888493851934[65] = 0;
   out_8717321888493851934[66] = dt;
   out_8717321888493851934[67] = 0;
   out_8717321888493851934[68] = 0;
   out_8717321888493851934[69] = 0;
   out_8717321888493851934[70] = 0;
   out_8717321888493851934[71] = 0;
   out_8717321888493851934[72] = 0;
   out_8717321888493851934[73] = 0;
   out_8717321888493851934[74] = 0;
   out_8717321888493851934[75] = 0;
   out_8717321888493851934[76] = 1;
   out_8717321888493851934[77] = 0;
   out_8717321888493851934[78] = 0;
   out_8717321888493851934[79] = 0;
   out_8717321888493851934[80] = 0;
   out_8717321888493851934[81] = 0;
   out_8717321888493851934[82] = 0;
   out_8717321888493851934[83] = 0;
   out_8717321888493851934[84] = 0;
   out_8717321888493851934[85] = dt;
   out_8717321888493851934[86] = 0;
   out_8717321888493851934[87] = 0;
   out_8717321888493851934[88] = 0;
   out_8717321888493851934[89] = 0;
   out_8717321888493851934[90] = 0;
   out_8717321888493851934[91] = 0;
   out_8717321888493851934[92] = 0;
   out_8717321888493851934[93] = 0;
   out_8717321888493851934[94] = 0;
   out_8717321888493851934[95] = 1;
   out_8717321888493851934[96] = 0;
   out_8717321888493851934[97] = 0;
   out_8717321888493851934[98] = 0;
   out_8717321888493851934[99] = 0;
   out_8717321888493851934[100] = 0;
   out_8717321888493851934[101] = 0;
   out_8717321888493851934[102] = 0;
   out_8717321888493851934[103] = 0;
   out_8717321888493851934[104] = dt;
   out_8717321888493851934[105] = 0;
   out_8717321888493851934[106] = 0;
   out_8717321888493851934[107] = 0;
   out_8717321888493851934[108] = 0;
   out_8717321888493851934[109] = 0;
   out_8717321888493851934[110] = 0;
   out_8717321888493851934[111] = 0;
   out_8717321888493851934[112] = 0;
   out_8717321888493851934[113] = 0;
   out_8717321888493851934[114] = 1;
   out_8717321888493851934[115] = 0;
   out_8717321888493851934[116] = 0;
   out_8717321888493851934[117] = 0;
   out_8717321888493851934[118] = 0;
   out_8717321888493851934[119] = 0;
   out_8717321888493851934[120] = 0;
   out_8717321888493851934[121] = 0;
   out_8717321888493851934[122] = 0;
   out_8717321888493851934[123] = 0;
   out_8717321888493851934[124] = 0;
   out_8717321888493851934[125] = 0;
   out_8717321888493851934[126] = 0;
   out_8717321888493851934[127] = 0;
   out_8717321888493851934[128] = 0;
   out_8717321888493851934[129] = 0;
   out_8717321888493851934[130] = 0;
   out_8717321888493851934[131] = 0;
   out_8717321888493851934[132] = 0;
   out_8717321888493851934[133] = 1;
   out_8717321888493851934[134] = 0;
   out_8717321888493851934[135] = 0;
   out_8717321888493851934[136] = 0;
   out_8717321888493851934[137] = 0;
   out_8717321888493851934[138] = 0;
   out_8717321888493851934[139] = 0;
   out_8717321888493851934[140] = 0;
   out_8717321888493851934[141] = 0;
   out_8717321888493851934[142] = 0;
   out_8717321888493851934[143] = 0;
   out_8717321888493851934[144] = 0;
   out_8717321888493851934[145] = 0;
   out_8717321888493851934[146] = 0;
   out_8717321888493851934[147] = 0;
   out_8717321888493851934[148] = 0;
   out_8717321888493851934[149] = 0;
   out_8717321888493851934[150] = 0;
   out_8717321888493851934[151] = 0;
   out_8717321888493851934[152] = 1;
   out_8717321888493851934[153] = 0;
   out_8717321888493851934[154] = 0;
   out_8717321888493851934[155] = 0;
   out_8717321888493851934[156] = 0;
   out_8717321888493851934[157] = 0;
   out_8717321888493851934[158] = 0;
   out_8717321888493851934[159] = 0;
   out_8717321888493851934[160] = 0;
   out_8717321888493851934[161] = 0;
   out_8717321888493851934[162] = 0;
   out_8717321888493851934[163] = 0;
   out_8717321888493851934[164] = 0;
   out_8717321888493851934[165] = 0;
   out_8717321888493851934[166] = 0;
   out_8717321888493851934[167] = 0;
   out_8717321888493851934[168] = 0;
   out_8717321888493851934[169] = 0;
   out_8717321888493851934[170] = 0;
   out_8717321888493851934[171] = 1;
   out_8717321888493851934[172] = 0;
   out_8717321888493851934[173] = 0;
   out_8717321888493851934[174] = 0;
   out_8717321888493851934[175] = 0;
   out_8717321888493851934[176] = 0;
   out_8717321888493851934[177] = 0;
   out_8717321888493851934[178] = 0;
   out_8717321888493851934[179] = 0;
   out_8717321888493851934[180] = 0;
   out_8717321888493851934[181] = 0;
   out_8717321888493851934[182] = 0;
   out_8717321888493851934[183] = 0;
   out_8717321888493851934[184] = 0;
   out_8717321888493851934[185] = 0;
   out_8717321888493851934[186] = 0;
   out_8717321888493851934[187] = 0;
   out_8717321888493851934[188] = 0;
   out_8717321888493851934[189] = 0;
   out_8717321888493851934[190] = 1;
   out_8717321888493851934[191] = 0;
   out_8717321888493851934[192] = 0;
   out_8717321888493851934[193] = 0;
   out_8717321888493851934[194] = 0;
   out_8717321888493851934[195] = 0;
   out_8717321888493851934[196] = 0;
   out_8717321888493851934[197] = 0;
   out_8717321888493851934[198] = 0;
   out_8717321888493851934[199] = 0;
   out_8717321888493851934[200] = 0;
   out_8717321888493851934[201] = 0;
   out_8717321888493851934[202] = 0;
   out_8717321888493851934[203] = 0;
   out_8717321888493851934[204] = 0;
   out_8717321888493851934[205] = 0;
   out_8717321888493851934[206] = 0;
   out_8717321888493851934[207] = 0;
   out_8717321888493851934[208] = 0;
   out_8717321888493851934[209] = 1;
   out_8717321888493851934[210] = 0;
   out_8717321888493851934[211] = 0;
   out_8717321888493851934[212] = 0;
   out_8717321888493851934[213] = 0;
   out_8717321888493851934[214] = 0;
   out_8717321888493851934[215] = 0;
   out_8717321888493851934[216] = 0;
   out_8717321888493851934[217] = 0;
   out_8717321888493851934[218] = 0;
   out_8717321888493851934[219] = 0;
   out_8717321888493851934[220] = 0;
   out_8717321888493851934[221] = 0;
   out_8717321888493851934[222] = 0;
   out_8717321888493851934[223] = 0;
   out_8717321888493851934[224] = 0;
   out_8717321888493851934[225] = 0;
   out_8717321888493851934[226] = 0;
   out_8717321888493851934[227] = 0;
   out_8717321888493851934[228] = 1;
   out_8717321888493851934[229] = 0;
   out_8717321888493851934[230] = 0;
   out_8717321888493851934[231] = 0;
   out_8717321888493851934[232] = 0;
   out_8717321888493851934[233] = 0;
   out_8717321888493851934[234] = 0;
   out_8717321888493851934[235] = 0;
   out_8717321888493851934[236] = 0;
   out_8717321888493851934[237] = 0;
   out_8717321888493851934[238] = 0;
   out_8717321888493851934[239] = 0;
   out_8717321888493851934[240] = 0;
   out_8717321888493851934[241] = 0;
   out_8717321888493851934[242] = 0;
   out_8717321888493851934[243] = 0;
   out_8717321888493851934[244] = 0;
   out_8717321888493851934[245] = 0;
   out_8717321888493851934[246] = 0;
   out_8717321888493851934[247] = 1;
   out_8717321888493851934[248] = 0;
   out_8717321888493851934[249] = 0;
   out_8717321888493851934[250] = 0;
   out_8717321888493851934[251] = 0;
   out_8717321888493851934[252] = 0;
   out_8717321888493851934[253] = 0;
   out_8717321888493851934[254] = 0;
   out_8717321888493851934[255] = 0;
   out_8717321888493851934[256] = 0;
   out_8717321888493851934[257] = 0;
   out_8717321888493851934[258] = 0;
   out_8717321888493851934[259] = 0;
   out_8717321888493851934[260] = 0;
   out_8717321888493851934[261] = 0;
   out_8717321888493851934[262] = 0;
   out_8717321888493851934[263] = 0;
   out_8717321888493851934[264] = 0;
   out_8717321888493851934[265] = 0;
   out_8717321888493851934[266] = 1;
   out_8717321888493851934[267] = 0;
   out_8717321888493851934[268] = 0;
   out_8717321888493851934[269] = 0;
   out_8717321888493851934[270] = 0;
   out_8717321888493851934[271] = 0;
   out_8717321888493851934[272] = 0;
   out_8717321888493851934[273] = 0;
   out_8717321888493851934[274] = 0;
   out_8717321888493851934[275] = 0;
   out_8717321888493851934[276] = 0;
   out_8717321888493851934[277] = 0;
   out_8717321888493851934[278] = 0;
   out_8717321888493851934[279] = 0;
   out_8717321888493851934[280] = 0;
   out_8717321888493851934[281] = 0;
   out_8717321888493851934[282] = 0;
   out_8717321888493851934[283] = 0;
   out_8717321888493851934[284] = 0;
   out_8717321888493851934[285] = 1;
   out_8717321888493851934[286] = 0;
   out_8717321888493851934[287] = 0;
   out_8717321888493851934[288] = 0;
   out_8717321888493851934[289] = 0;
   out_8717321888493851934[290] = 0;
   out_8717321888493851934[291] = 0;
   out_8717321888493851934[292] = 0;
   out_8717321888493851934[293] = 0;
   out_8717321888493851934[294] = 0;
   out_8717321888493851934[295] = 0;
   out_8717321888493851934[296] = 0;
   out_8717321888493851934[297] = 0;
   out_8717321888493851934[298] = 0;
   out_8717321888493851934[299] = 0;
   out_8717321888493851934[300] = 0;
   out_8717321888493851934[301] = 0;
   out_8717321888493851934[302] = 0;
   out_8717321888493851934[303] = 0;
   out_8717321888493851934[304] = 1;
   out_8717321888493851934[305] = 0;
   out_8717321888493851934[306] = 0;
   out_8717321888493851934[307] = 0;
   out_8717321888493851934[308] = 0;
   out_8717321888493851934[309] = 0;
   out_8717321888493851934[310] = 0;
   out_8717321888493851934[311] = 0;
   out_8717321888493851934[312] = 0;
   out_8717321888493851934[313] = 0;
   out_8717321888493851934[314] = 0;
   out_8717321888493851934[315] = 0;
   out_8717321888493851934[316] = 0;
   out_8717321888493851934[317] = 0;
   out_8717321888493851934[318] = 0;
   out_8717321888493851934[319] = 0;
   out_8717321888493851934[320] = 0;
   out_8717321888493851934[321] = 0;
   out_8717321888493851934[322] = 0;
   out_8717321888493851934[323] = 1;
}
void h_4(double *state, double *unused, double *out_8181067520651079542) {
   out_8181067520651079542[0] = state[6] + state[9];
   out_8181067520651079542[1] = state[7] + state[10];
   out_8181067520651079542[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_1593126237582888921) {
   out_1593126237582888921[0] = 0;
   out_1593126237582888921[1] = 0;
   out_1593126237582888921[2] = 0;
   out_1593126237582888921[3] = 0;
   out_1593126237582888921[4] = 0;
   out_1593126237582888921[5] = 0;
   out_1593126237582888921[6] = 1;
   out_1593126237582888921[7] = 0;
   out_1593126237582888921[8] = 0;
   out_1593126237582888921[9] = 1;
   out_1593126237582888921[10] = 0;
   out_1593126237582888921[11] = 0;
   out_1593126237582888921[12] = 0;
   out_1593126237582888921[13] = 0;
   out_1593126237582888921[14] = 0;
   out_1593126237582888921[15] = 0;
   out_1593126237582888921[16] = 0;
   out_1593126237582888921[17] = 0;
   out_1593126237582888921[18] = 0;
   out_1593126237582888921[19] = 0;
   out_1593126237582888921[20] = 0;
   out_1593126237582888921[21] = 0;
   out_1593126237582888921[22] = 0;
   out_1593126237582888921[23] = 0;
   out_1593126237582888921[24] = 0;
   out_1593126237582888921[25] = 1;
   out_1593126237582888921[26] = 0;
   out_1593126237582888921[27] = 0;
   out_1593126237582888921[28] = 1;
   out_1593126237582888921[29] = 0;
   out_1593126237582888921[30] = 0;
   out_1593126237582888921[31] = 0;
   out_1593126237582888921[32] = 0;
   out_1593126237582888921[33] = 0;
   out_1593126237582888921[34] = 0;
   out_1593126237582888921[35] = 0;
   out_1593126237582888921[36] = 0;
   out_1593126237582888921[37] = 0;
   out_1593126237582888921[38] = 0;
   out_1593126237582888921[39] = 0;
   out_1593126237582888921[40] = 0;
   out_1593126237582888921[41] = 0;
   out_1593126237582888921[42] = 0;
   out_1593126237582888921[43] = 0;
   out_1593126237582888921[44] = 1;
   out_1593126237582888921[45] = 0;
   out_1593126237582888921[46] = 0;
   out_1593126237582888921[47] = 1;
   out_1593126237582888921[48] = 0;
   out_1593126237582888921[49] = 0;
   out_1593126237582888921[50] = 0;
   out_1593126237582888921[51] = 0;
   out_1593126237582888921[52] = 0;
   out_1593126237582888921[53] = 0;
}
void h_10(double *state, double *unused, double *out_4029725787131848622) {
   out_4029725787131848622[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_4029725787131848622[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_4029725787131848622[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_7172679610378254733) {
   out_7172679610378254733[0] = 0;
   out_7172679610378254733[1] = 9.8100000000000005*cos(state[1]);
   out_7172679610378254733[2] = 0;
   out_7172679610378254733[3] = 0;
   out_7172679610378254733[4] = -state[8];
   out_7172679610378254733[5] = state[7];
   out_7172679610378254733[6] = 0;
   out_7172679610378254733[7] = state[5];
   out_7172679610378254733[8] = -state[4];
   out_7172679610378254733[9] = 0;
   out_7172679610378254733[10] = 0;
   out_7172679610378254733[11] = 0;
   out_7172679610378254733[12] = 1;
   out_7172679610378254733[13] = 0;
   out_7172679610378254733[14] = 0;
   out_7172679610378254733[15] = 1;
   out_7172679610378254733[16] = 0;
   out_7172679610378254733[17] = 0;
   out_7172679610378254733[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_7172679610378254733[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_7172679610378254733[20] = 0;
   out_7172679610378254733[21] = state[8];
   out_7172679610378254733[22] = 0;
   out_7172679610378254733[23] = -state[6];
   out_7172679610378254733[24] = -state[5];
   out_7172679610378254733[25] = 0;
   out_7172679610378254733[26] = state[3];
   out_7172679610378254733[27] = 0;
   out_7172679610378254733[28] = 0;
   out_7172679610378254733[29] = 0;
   out_7172679610378254733[30] = 0;
   out_7172679610378254733[31] = 1;
   out_7172679610378254733[32] = 0;
   out_7172679610378254733[33] = 0;
   out_7172679610378254733[34] = 1;
   out_7172679610378254733[35] = 0;
   out_7172679610378254733[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_7172679610378254733[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_7172679610378254733[38] = 0;
   out_7172679610378254733[39] = -state[7];
   out_7172679610378254733[40] = state[6];
   out_7172679610378254733[41] = 0;
   out_7172679610378254733[42] = state[4];
   out_7172679610378254733[43] = -state[3];
   out_7172679610378254733[44] = 0;
   out_7172679610378254733[45] = 0;
   out_7172679610378254733[46] = 0;
   out_7172679610378254733[47] = 0;
   out_7172679610378254733[48] = 0;
   out_7172679610378254733[49] = 0;
   out_7172679610378254733[50] = 1;
   out_7172679610378254733[51] = 0;
   out_7172679610378254733[52] = 0;
   out_7172679610378254733[53] = 1;
}
void h_13(double *state, double *unused, double *out_473946471737287856) {
   out_473946471737287856[0] = state[3];
   out_473946471737287856[1] = state[4];
   out_473946471737287856[2] = state[5];
}
void H_13(double *state, double *unused, double *out_1619147587749443880) {
   out_1619147587749443880[0] = 0;
   out_1619147587749443880[1] = 0;
   out_1619147587749443880[2] = 0;
   out_1619147587749443880[3] = 1;
   out_1619147587749443880[4] = 0;
   out_1619147587749443880[5] = 0;
   out_1619147587749443880[6] = 0;
   out_1619147587749443880[7] = 0;
   out_1619147587749443880[8] = 0;
   out_1619147587749443880[9] = 0;
   out_1619147587749443880[10] = 0;
   out_1619147587749443880[11] = 0;
   out_1619147587749443880[12] = 0;
   out_1619147587749443880[13] = 0;
   out_1619147587749443880[14] = 0;
   out_1619147587749443880[15] = 0;
   out_1619147587749443880[16] = 0;
   out_1619147587749443880[17] = 0;
   out_1619147587749443880[18] = 0;
   out_1619147587749443880[19] = 0;
   out_1619147587749443880[20] = 0;
   out_1619147587749443880[21] = 0;
   out_1619147587749443880[22] = 1;
   out_1619147587749443880[23] = 0;
   out_1619147587749443880[24] = 0;
   out_1619147587749443880[25] = 0;
   out_1619147587749443880[26] = 0;
   out_1619147587749443880[27] = 0;
   out_1619147587749443880[28] = 0;
   out_1619147587749443880[29] = 0;
   out_1619147587749443880[30] = 0;
   out_1619147587749443880[31] = 0;
   out_1619147587749443880[32] = 0;
   out_1619147587749443880[33] = 0;
   out_1619147587749443880[34] = 0;
   out_1619147587749443880[35] = 0;
   out_1619147587749443880[36] = 0;
   out_1619147587749443880[37] = 0;
   out_1619147587749443880[38] = 0;
   out_1619147587749443880[39] = 0;
   out_1619147587749443880[40] = 0;
   out_1619147587749443880[41] = 1;
   out_1619147587749443880[42] = 0;
   out_1619147587749443880[43] = 0;
   out_1619147587749443880[44] = 0;
   out_1619147587749443880[45] = 0;
   out_1619147587749443880[46] = 0;
   out_1619147587749443880[47] = 0;
   out_1619147587749443880[48] = 0;
   out_1619147587749443880[49] = 0;
   out_1619147587749443880[50] = 0;
   out_1619147587749443880[51] = 0;
   out_1619147587749443880[52] = 0;
   out_1619147587749443880[53] = 0;
}
void h_14(double *state, double *unused, double *out_7656295873946429583) {
   out_7656295873946429583[0] = state[6];
   out_7656295873946429583[1] = state[7];
   out_7656295873946429583[2] = state[8];
}
void H_14(double *state, double *unused, double *out_2370114618756595608) {
   out_2370114618756595608[0] = 0;
   out_2370114618756595608[1] = 0;
   out_2370114618756595608[2] = 0;
   out_2370114618756595608[3] = 0;
   out_2370114618756595608[4] = 0;
   out_2370114618756595608[5] = 0;
   out_2370114618756595608[6] = 1;
   out_2370114618756595608[7] = 0;
   out_2370114618756595608[8] = 0;
   out_2370114618756595608[9] = 0;
   out_2370114618756595608[10] = 0;
   out_2370114618756595608[11] = 0;
   out_2370114618756595608[12] = 0;
   out_2370114618756595608[13] = 0;
   out_2370114618756595608[14] = 0;
   out_2370114618756595608[15] = 0;
   out_2370114618756595608[16] = 0;
   out_2370114618756595608[17] = 0;
   out_2370114618756595608[18] = 0;
   out_2370114618756595608[19] = 0;
   out_2370114618756595608[20] = 0;
   out_2370114618756595608[21] = 0;
   out_2370114618756595608[22] = 0;
   out_2370114618756595608[23] = 0;
   out_2370114618756595608[24] = 0;
   out_2370114618756595608[25] = 1;
   out_2370114618756595608[26] = 0;
   out_2370114618756595608[27] = 0;
   out_2370114618756595608[28] = 0;
   out_2370114618756595608[29] = 0;
   out_2370114618756595608[30] = 0;
   out_2370114618756595608[31] = 0;
   out_2370114618756595608[32] = 0;
   out_2370114618756595608[33] = 0;
   out_2370114618756595608[34] = 0;
   out_2370114618756595608[35] = 0;
   out_2370114618756595608[36] = 0;
   out_2370114618756595608[37] = 0;
   out_2370114618756595608[38] = 0;
   out_2370114618756595608[39] = 0;
   out_2370114618756595608[40] = 0;
   out_2370114618756595608[41] = 0;
   out_2370114618756595608[42] = 0;
   out_2370114618756595608[43] = 0;
   out_2370114618756595608[44] = 1;
   out_2370114618756595608[45] = 0;
   out_2370114618756595608[46] = 0;
   out_2370114618756595608[47] = 0;
   out_2370114618756595608[48] = 0;
   out_2370114618756595608[49] = 0;
   out_2370114618756595608[50] = 0;
   out_2370114618756595608[51] = 0;
   out_2370114618756595608[52] = 0;
   out_2370114618756595608[53] = 0;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_4, H_4, NULL, in_z, in_R, in_ea, MAHA_THRESH_4);
}
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_10, H_10, NULL, in_z, in_R, in_ea, MAHA_THRESH_10);
}
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_13, H_13, NULL, in_z, in_R, in_ea, MAHA_THRESH_13);
}
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_14, H_14, NULL, in_z, in_R, in_ea, MAHA_THRESH_14);
}
void pose_err_fun(double *nom_x, double *delta_x, double *out_1103084970822345352) {
  err_fun(nom_x, delta_x, out_1103084970822345352);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_5459115001706413123) {
  inv_err_fun(nom_x, true_x, out_5459115001706413123);
}
void pose_H_mod_fun(double *state, double *out_7351235428474932421) {
  H_mod_fun(state, out_7351235428474932421);
}
void pose_f_fun(double *state, double dt, double *out_5276878112375474914) {
  f_fun(state,  dt, out_5276878112375474914);
}
void pose_F_fun(double *state, double dt, double *out_8717321888493851934) {
  F_fun(state,  dt, out_8717321888493851934);
}
void pose_h_4(double *state, double *unused, double *out_8181067520651079542) {
  h_4(state, unused, out_8181067520651079542);
}
void pose_H_4(double *state, double *unused, double *out_1593126237582888921) {
  H_4(state, unused, out_1593126237582888921);
}
void pose_h_10(double *state, double *unused, double *out_4029725787131848622) {
  h_10(state, unused, out_4029725787131848622);
}
void pose_H_10(double *state, double *unused, double *out_7172679610378254733) {
  H_10(state, unused, out_7172679610378254733);
}
void pose_h_13(double *state, double *unused, double *out_473946471737287856) {
  h_13(state, unused, out_473946471737287856);
}
void pose_H_13(double *state, double *unused, double *out_1619147587749443880) {
  H_13(state, unused, out_1619147587749443880);
}
void pose_h_14(double *state, double *unused, double *out_7656295873946429583) {
  h_14(state, unused, out_7656295873946429583);
}
void pose_H_14(double *state, double *unused, double *out_2370114618756595608) {
  H_14(state, unused, out_2370114618756595608);
}
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
}

const EKF pose = {
  .name = "pose",
  .kinds = { 4, 10, 13, 14 },
  .feature_kinds = {  },
  .f_fun = pose_f_fun,
  .F_fun = pose_F_fun,
  .err_fun = pose_err_fun,
  .inv_err_fun = pose_inv_err_fun,
  .H_mod_fun = pose_H_mod_fun,
  .predict = pose_predict,
  .hs = {
    { 4, pose_h_4 },
    { 10, pose_h_10 },
    { 13, pose_h_13 },
    { 14, pose_h_14 },
  },
  .Hs = {
    { 4, pose_H_4 },
    { 10, pose_H_10 },
    { 13, pose_H_13 },
    { 14, pose_H_14 },
  },
  .updates = {
    { 4, pose_update_4 },
    { 10, pose_update_10 },
    { 13, pose_update_13 },
    { 14, pose_update_14 },
  },
  .Hes = {
  },
  .sets = {
  },
  .extra_routines = {
  },
};

ekf_lib_init(pose)
