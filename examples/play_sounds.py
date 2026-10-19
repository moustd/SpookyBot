
import random
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy.signal import resample_poly

# --------------------------------------------------
# Configuration
# --------------------------------------------------

SOUND_DIRS = {
    "thunder": Path("sounds/thunder"),
    "screams": Path("sounds/screams"),
    "spooky": Path("sounds/spooky"),
}

VOLUMES = {
    "thunder": 1.0,
    "screams": 1.0,
    "spooky": 0.8,
}

SAMPLE_RATE = 44100
FADE_IN = 0.5
FADE_OUT = 0.5

DELAYS = {
    "thunder": (0.0, 0.0),
    "screams": (1.5, 2.5),
    "spooky": (0.8, 1.2),
}

# Preloaded and processed sounds, ready for playback
SOUND_CACHE = {}


# --------------------------------------------------
# Audio preparation - runs once at startup
# --------------------------------------------------

def prepare_sound(filename, category):
    audio, sample_rate = sf.read(filename, dtype="float32")

    # Convert stereo sources to mono
    if audio.ndim == 2:
        audio = audio.mean(axis=1, dtype=np.float32)

    # Resample once, rather than during playback
    if sample_rate != SAMPLE_RATE:
        factor = gcd(sample_rate, SAMPLE_RATE)
        audio = resample_poly(
            audio,
            SAMPLE_RATE // factor,
            sample_rate // factor,
        ).astype(np.float32, copy=False)

    length = len(audio)

    # Apply volume directly to the audio
    audio *= VOLUMES[category]

    # Precalculate and apply fades
    fade_in_samples = min(int(FADE_IN * SAMPLE_RATE), length)
    fade_out_samples = min(int(FADE_OUT * SAMPLE_RATE), length)

    if fade_in_samples:
        audio[:fade_in_samples] *= np.linspace(
            0.0, 1.0, fade_in_samples, dtype=np.float32
        )

    if fade_out_samples:
        audio[-fade_out_samples:] *= np.linspace(
            1.0, 0.0, fade_out_samples, dtype=np.float32
        )

    # Store contiguous audio for efficient mixing
    return np.ascontiguousarray(audio)


def preload_sounds():
    """Load and process all sounds once at startup."""
    print("Preloading sounds...")

    for category, directory in SOUND_DIRS.items():
        files = [
            f for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() == ".wav"
        ]

        if not files:
            raise FileNotFoundError(
                f"No WAV files found in {directory}"
            )

        SOUND_CACHE[category] = []

        for filename in files:
            audio = prepare_sound(filename, category)
            SOUND_CACHE[category].append((filename.name, audio))

        print(f"  {category}: {len(files)} sounds loaded")

    print("All sounds ready.\n")


# --------------------------------------------------
# Playback - uses preloaded audio
# --------------------------------------------------

def play_random_mix():
    # Random selection requires no file reading or resampling
    sounds = {}
    for category, cached_sounds in SOUND_CACHE.items():
        filename, audio = random.choice(cached_sounds)
        sounds[category] = audio
        print(f"Selected {category}: {filename}")

    # Choose start delays
    delays = {
        category: random.uniform(*DELAYS[category])
        for category in sounds
    }

    # Calculate the required output length
    starts = {
        category: int(delays[category] * SAMPLE_RATE)
        for category in sounds
    }

    total_length = max(
        starts[category] + len(audio)
        for category, audio in sounds.items()
    )

    # Stereo output
    mix = np.zeros((total_length, 2), dtype=np.float32)

    # Mix the already processed audio
    for category, audio in sounds.items():
        start = starts[category]
        end = start + len(audio)

        if category == "thunder":
            mix[start:end, 0] += audio
            mix[start:end, 1] += audio

        elif category == "screams":
            mix[start:end, 0] += audio

        elif category == "spooky":
            mix[start:end, 1] += audio

    # Prevent clipping
    peak = np.max(np.abs(mix))
    if peak > 1.0:
        mix /= peak

    print("Playing...")
    sd.play(mix, SAMPLE_RATE)
    sd.wait()
    print("Playback finished.")


# --------------------------------------------------
# Main
# --------------------------------------------------

if __name__ == "__main__":
    preload_sounds()

    play_random_mix()
