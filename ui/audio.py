"""
ui/audio.py – Alert sound tones generated with NumPy and pygame.mixer.

Produces distinct alert audio for:
  - Warning 1: Double high-frequency alert tone (danger detected ahead).
  - Warning 2: Reassuring confirmation chime (safe detour calculated).

Robustness (Section 15):
  Audio failures or absence of audio hardware are caught and logged silently,
  ensuring visual simulation warnings continue without interruption.
"""

import math
import numpy as np
import pygame


class AudioManager:
    """Manages synthetic alert sounds via pygame.mixer."""

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate
        self.audio_available = False
        self.sound_warning_1: Optional[pygame.mixer.Sound] = None
        self.sound_warning_2: Optional[pygame.mixer.Sound] = None

        self._init_audio()

    def _init_audio(self) -> None:
        """Attempt to initialize pygame.mixer and synthesize tone waveforms."""
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.sample_rate, size=-16, channels=1, buffer=512)

            # Generate Warning 1: 880 Hz double beep
            self.sound_warning_1 = self._generate_beep(freq=880.0, duration=0.12, double=True)

            # Generate Warning 2: 587 Hz (D5) confirmation chime
            self.sound_warning_2 = self._generate_beep(freq=587.33, duration=0.20, double=False)

            self.audio_available = True
        except Exception as e:
            # Silently catch: visual simulation continues unaffected
            self.audio_available = False

    def _generate_beep(self, freq: float, duration: float, double: bool = False) -> pygame.mixer.Sound:
        """Synthesize a smooth sine-wave beep using NumPy."""
        n_samples = int(self.sample_rate * duration)
        t = np.linspace(0, duration, n_samples, endpoint=False)

        # Sine wave with exponential envelope decay to prevent clicking
        envelope = np.exp(-3.0 * t / duration)
        waveform = 0.5 * np.sin(2.0 * np.pi * freq * t) * envelope

        if double:
            silence = np.zeros(int(self.sample_rate * 0.05))
            waveform = np.concatenate([waveform, silence, waveform])

        audio_int16 = (waveform * 32767).astype(np.int16)
        return pygame.sndarray.make_sound(audio_int16)

    def play_warning_1(self) -> None:
        """Play Warning 1 alert tone."""
        if self.audio_available and self.sound_warning_1:
            try:
                self.sound_warning_1.play()
            except Exception:
                pass

    def play_warning_2(self) -> None:
        """Play Warning 2 confirmation tone."""
        if self.audio_available and self.sound_warning_2:
            try:
                self.sound_warning_2.play()
            except Exception:
                pass
