Done in VS code using Python 313

dependencies:
pip install numpy pillow matplotlib


<img width="731" height="407" alt="Screenshot 2025-11-02 094937" src="https://github.com/user-attachments/assets/503ea6d4-0a8f-4d28-a1f5-c9288684bd9b" />

How This Works
bladeRF/hackrf Spectrum Painter turns an image—or auto-scaled text—into complex IQ samples and transmits them with bladeRF-cli so your spectrum/waterfall literally “draws” the picture.
At a high level:
Raster source
Image mode: load an image and resize to Raster W × Raster H.
Text mode: render a word/phrase to a grayscale bitmap. The renderer auto-scales the font to fit both width and height (no clipping), then centers it.
Optional Invert colors flips white↔black in the bitmap (amplitude inversion only; no flipping in time or frequency).
Row-by-row synthesis
The bitmap is scanned top→bottom. Each row becomes a short FM chirp burst whose amplitude follows pixel brightness across the row:
Let rows_per_s be the “Speed” control. Row duration: Trow = 1 / rows_per_s.
Each row sweeps a bandwidth BW linearly over Trow (classic LFM chirp).
Pixel values along the row (0…255) are resampled onto the audio time grid and used as a real amplitude envelope for the chirp.

FM chirp modulation (the engine)
We synthesize a complex phasor e^{jφ(t)} where the instantaneous frequency is linear in time:
USB (single-sideband, avoids DC):
f(t) = f_min + (BW/Trow)·t
DSB (centered around DC):
f(t) = −BW/2 + (BW/Trow)·t
Phase integrates frequency:
φ(t) = 2π ( f0·t + 0.5·(BW/Trow)·t² )
The row’s amplitude envelope multiplies this chirp → a straight, bright line in the waterfall wherever pixels are light.

Concatenate rows → IQ stream
All row segments are concatenated to form a single complex array. This step uses multiprocessing (one worker per CPU minus one) for speed.
Signal conditioning & packing
DC-block: subtract mean (reduces residual center spike).
Normalize: scale to ~95% FS to avoid DAC clipping.
Quantize: interleave I/Q to SC16 Q11 (±2047) raw binary for bladeRF.

bladeRF control
The app starts bladeRF-cli in interactive mode, then sends:

set samplerate tx <Fs>
set frequency  tx <Fc>
set bandwidth  tx <BW>
set gain       tx <dB>
tx config file="paint.bin" format=bin repeat=<0|1>
tx start

If not looping, it uses tx wait then tx stop so the file always finishes cleanly.
Key Controls (and what they mean)
Freq (MHz): RF center frequency Fc.
BW (kHz): chirp span per row. Wider BW = wider picture across frequency.
Sample-rate (MHz): DAC rate Fs. The code clamps BW ≤ 0.9·Fs to respect Nyquist.
Speed (rows/s): raster scan rate. Higher speed → shorter Trow → steeper chirp slope.
Raster W × H: rendering resolution. Larger W = finer frequency detail; larger H = more rows (longer message).
USB (single-sideband): sweeps [f_min, f_min+BW] above DC; cleaner center.
USB fmin (kHz): sets f_min offset (e.g., 10–50 kHz) to keep energy away from DC.
Invert colors: inverts bitmap grayscale before synthesis (flips amplitude, not chirp direction).
Power (dB): bladeRF TX gain. IQ is pre-normalized; this sets RF output level.
Repeat: loop transmission (repeat=0 to loop; repeat=1 to play once—this matches bladeRF-cli semantics).

Data & Math Snapshot
Row duration: Trow = 1 / rows_per_s
Samples per row: Ns = round(Fs · Trow)
Chirp frequency:
USB: f(t) = f_min + (BW/Trow) t
DSB: f(t) = −BW/2 + (BW/Trow) t
Phase: φ(t) = 2π ( f0 t + ½ (BW/Trow) t² )
Complex baseband: x_row(t) = a_row(t) · e^{jφ(t)} with a_row(t) ∈ [0,1] from the row’s pixel intensity.
Final IQ: concatenate x_row over all rows, DC-block, normalize, then pack to SC16 Q11.
Performance Considerations
Multiprocessing across rows accelerates generation on multi-core systems.
USB mode + small fmin helps keep the center bin clean on analyzers.
Raster W heavily influences sharpness of diagonal/curved edges in frequency; Raster H sets total transmit time (H / rows_per_s).
For long words, the auto-scaler shrinks font to fit both dimensions; for maximum crispness, increase Raster W.

Typical Workflow
Launch the app.
Choose Text (default “HELLO”) or load an Image.
Optionally Invert colors.
Set Fc, Fs, BW, Power, Speed, Raster W/H.
Pick USB (and fmin) or DSB.
Click Play. The app builds paint.bin, configures bladeRF, and transmits.
On a spectrum/waterfall viewer, watch the picture get “painted” in RF.

Notes & Extensions
The app uses classic tk widgets with a dark palette (works cleanly on Windows).
It searches for bladeRF-cli.exe in C:\bladeRF, Program Files (x86/64), or the system PATH.

Easy extensions:
Polarity toggle (multiply the complex signal by −1 to invert spectral polarity).
Gamma/contrast mapping on the bitmap for mid-tone emphasis.
Multi-band art: split the image into stripes and assign each to a different RF sub-band.
Offline preview: render a simulated waterfall next to the controls.

<img width="1099" height="650" alt="Screenshot 2025-11-02 094823" src="https://github.com/user-attachments/assets/2ef6758a-ad84-41a3-a44d-c5adf1bf00cf" />
