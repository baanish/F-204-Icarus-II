# Icarus engine audio

Three seamless mono 44.1 kHz PCM24 loops, the owner's choice from the audio research (round 7, take A, "Clean, dark F110 roar: complete engine"). The recording is an F110-GE-100 afterburning turbofan in a hush house, standing in for the J79: it is not J79 audio.

| File | Role | SHA-256 |
|---|---|---|
| `turbine_a_f110_r6.wav` | Turbine whine (Turbojet.turbineAudio) | `4996c924989a6af80480abef6bed0f359dfab96f9e0ad6924cc8029cfd4b52e4` |
| `dry_a_f110_r7.wav` | Dry thrust roar (JetNozzle.thrustAudio) | `7e3cc921d8a8b1cffb19d145f1c0de5eeac7a049022c09b0978b7e47a52a22dd` |
| `afterburner_m_f110_r6.wav` | Reheat (the afterburner's source, plus +9.53 dB from ReheatGain) | `005859fcc96622ff96f9a389d23962890948266da648ce83bd17f1d8d60a4f81` |

## Source

"177th Fighter Wing gas turbine engine testing" by USAF / New Jersey Air National Guard, Master Sgt. Andrew Moseley, VIRIN 170131-Z-YH452-001, 31 January 2017, https://www.dvidshub.net/video/512154/177th-fighter-wing-gas-turbine-engine-testing . Public domain per the DVIDS item and https://www.dvidshub.net/about/copyright . The appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.

## How each loop was made

- **Turbine:** an Earshot v0.4.0 gesture fit of the dry hold at 74-78 s, slowed 0.4537 so the fan line sits at 813 Hz (1,220 Hz at full RPM). Every tonal line is a constant partial snapped to whole cycles in a 15 s loop, over a roar rendered from earlier fits of the same recording, shaped with fixed shelves, its crest lowered by magnitude-preserving shaping and its level set by linear gain.
- **Dry roar:** the dry run at 72-82 s, low-passed at 500 Hz with a small bass shelf, its 56 Hz engine-order line ladder removed in the STFT, 250-400 Hz eased 3 dB, magnitude-preserving crest shaping and linear gain to -12 LUFS.
- **Reheat:** Earshot v0.4.0 spectral renders fitted from the recording's static reheat hold (292-304 s), with oversampled band-limited saturation (nothing above 5.5 kHz), a 30-90 Hz rasp at 700-4,000 Hz, a sub boost with slow random level movement and generated crackle transients; true peak set by linear gain to -1.2 dBTP.

No owner-supplied reference audio and no Nuclear Option stock audio enters any loop; they were measurement references only.

[Earshot](https://github.com/Leonxlnx/earshot) v0.4.0, copyright 2026 Leon Lin, MIT licence, was the synthesis tool; its output carries no Earshot code.
