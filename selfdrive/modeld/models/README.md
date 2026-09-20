## Neural networks in openpilot
To view the architecture of the ONNX networks, you can use [netron](https://netron.app/)

## Driving Model (vision model + temporal policy model)
### Vision inputs (Full size: 799906 x float32)
* **image stream**
  * Two consecutive images (256 * 512 * 3 in RGB) recorded at 20 Hz : 393216 = 2 * 6 * 128 * 256
    * Each 256 * 512 image is represented in YUV420 with 6 channels : 6 * 128 * 256
      * Channels 0,1,2,3 represent the full-res Y channel and are represented in numpy as Y[::2, ::2], Y[::2, 1::2], Y[1::2, ::2], and Y[1::2, 1::2]
      * Channel 4 represents the half-res U channel
      * Channel 5 represents the half-res V channel
* **wide image stream**
  * Two consecutive images (256 * 512 * 3 in RGB) recorded at 20 Hz : 393216 = 2 * 6 * 128 * 256
    * Each 256 * 512 image is represented in YUV420 with 6 channels : 6 * 128 * 256
      * Channels 0,1,2,3 represent the full-res Y channel and are represented in numpy as Y[::2, ::2], Y[::2, 1::2], Y[1::2, ::2], and Y[1::2, 1::2]
      * Channel 4 represents the half-res U channel
      * Channel 5 represents the half-res V channel
### Policy inputs
* **desire**
  * one-hot encoded buffer to command model to execute certain actions, bit needs to be sent for the past 5 seconds (at 20FPS) : 100 * 8
* **traffic convention**
  * one-hot encoded vector to tell model whether traffic is right-hand or left-hand traffic : 2
* **lateral control params**
  * speed and steering delay for predicting the desired curvature: 2
* **previous desired curvatures**
  * vector of previously predicted desired curvatures: 100 * 1
* **feature buffer**
  * a buffer of intermediate features including the current feature to form a 5 seconds temporal context (at 20FPS) : 100 * 512


### Driving Model output format (Full size: XXX x float32)
Refer to **slice_outputs** and **parse_vision_outputs/parse_policy_outputs** in modeld.


## Driver Monitoring Model
* .onnx model can be run with onnx runtimes
* Source: commaai/openpilot master at `1b1b60ba93bf70d3a37bc306a02048fc71dd0b2c` (2026-09-19).
* Super Leicht checkpoint: `a9462a65-1886-462a-8847-ad4624d9abfc/200`.
* ONNX SHA-256: `dee5a294e8afaacc9295ac5d100e00733ecac278e79264b96331e40a3ede1b04`.
* Uses this branch's existing OpenCL/tinygrad runner and metadata extraction; rebuild the DM metadata and compiled model after updating.

### input format
* single image W = 1440 H = 960 luminance channel (Y) from the planar YUV420 format:
  * full input size is 1440 * 960 = 1382400
  * uint8 values ranging from 0 to 255
* camera calibration angles (roll, pitch, yaw) from liveCalibration: 3 x float32 inputs

### output format
* 553 outputs. The ONNX output is float16 and the runtime parser normalizes it to contiguous float32.
* Each driver side includes face pose and uncertainty descriptors plus face, eye, blink, sunglasses, phone, and sleep probabilities.
* Common outputs include wheel-side probability and 512 model features.
