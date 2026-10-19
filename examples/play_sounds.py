
import random
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy.signal import resample_poly

# Sound directories
SOUND_DIRS = {
    "thunder": Path("sounds/thunder"),
    "screams": Path("sounds/screams"),
    "spooky": Path("sounds/spooky"),
}

# Volume per sound (0.0 to 1.0)
VOLUMES = {
    "thunder": 1,
    "screams": 1,
    "spooky": 0.8,
}

SAMPLE_RATE = 44100
FADE_IN = 0.5
FADE_OUT = 0.5

# Delay before each sound starts, in seconds
DELAYS = {
    "thunder": (0.0, 0.0),
    "screams": (1.0, 2.0),
    "spooky": (0.8, 1.2),
}


def load_random_sound(directory):
    files = [
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() == ".wav"
    ]

    if not files:
        raise FileNotFoundError(f"No WAV files found in {directory}")

    filename = random.choice(files)
    audio, sample_rate = sf.read(filename, dtype="float32")

    # All source WAVs are mono
    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    # Resample if required
    if sample_rate != SAMPLE_RATE:
        factor = gcd(sample_rate, SAMPLE_RATE)
        audio = resample_poly(
            audio,
            SAMPLE_RATE // factor,
            sample_rate // factor,
        ).astype(np.float32)

    print(f"Selected {directory.name}: {filename.name}")
    return audio


def apply_fades(audio, volume):
    audio = audio.copy()
    length = len(audio)

    fade_in_samples = min(int(FADE_IN * SAMPLE_RATE), length)
    fade_out_samples = min(int(FADE_OUT * SAMPLE_RATE), length)

    envelope = np.ones(length, dtype=np.float32)

    if fade_in_samples:
        envelope[:fade_in_samples] = np.linspace(
            0, 1, fade_in_samples, dtype=np.float32
        )

    if fade_out_samples:
        envelope[-fade_out_samples:] *= np.linspace(
            1, 0, fade_out_samples, dtype=np.float32
        )

    return audio * envelope * volume


def main():
    sounds = {
        name: load_random_sound(directory)
        for name, directory in SOUND_DIRS.items()
    }

    delays = {
        name: random.uniform(*DELAYS[name])
        for name in sounds
    }

    # Stereo output: column 0 = left, column 1 = right
    total_length = max(
        int(delays[name] * SAMPLE_RATE) + len(audio)
        for name, audio in sounds.items()
    )

    mix = np.zeros((total_length, 2), dtype=np.float32)

    for name, audio in sounds.items():
        audio = apply_fades(audio, VOLUMES[name])

        start = int(delays[name] * SAMPLE_RATE)
        end = start + len(audio)

        if name == "thunder":
            # Thunder plays in both channels
            mix[start:end, 0] += audio
            mix[start:end, 1] += audio

        elif name == "screams":
            # Screams play only on the left
            mix[start:end, 0] += audio

        elif name == "spooky":
            # Spooky plays only on the right
            mix[start:end, 1] += audio

    # Prevent clipping while preserving stereo placement
    peak = np.max(np.abs(mix))
    if peak > 1.0:
        mix /= peak

    print("Playing stereo mix...")
    sd.play(mix, SAMPLE_RATE)
    sd.wait()
    print("Playback finished.")


if __name__ == "__main__":
    main()
