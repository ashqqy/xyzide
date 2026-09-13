"""Sound for the arena.

Every effect is synthesised with numpy at start-up, so no audio assets ship
with the game.  A single long-lived player process is fed raw PCM once per
frame, which means overlapping effects mix properly instead of spawning one
process per gunshot.  If no player is available the whole thing turns into a
no-op and the game runs silently.
"""

import os
import subprocess

import numpy as np

RATE = 22050
MAX_VOICES = 14
MAX_BACKLOG = RATE          # never buffer more than a second

# Raw signed 16-bit mono on stdin, cheapest first.
PLAYERS = (
    ["pacat", "-p", "--format=s16le", f"--rate={RATE}", "--channels=1",
     "--latency-msec=60", "--stream-name=xyzide-arena"],
    ["pw-cat", "-p", "--raw", "--format", "s16", "--rate", str(RATE),
     "--channels", "1", "--latency", "60ms", "-"],
    ["aplay", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw", "-"],
)


# ------------------------------------------------------------------ synthesis

def _t(dur):
    return np.arange(max(1, int(RATE * dur)), dtype=np.float32) / RATE


def _decay(t, rate, attack=0.004):
    env = np.exp(-t * rate)
    rise = np.clip(t / max(attack, 1e-5), 0.0, 1.0)
    return env * rise


def _sweep(f0, f1, dur, decay=8.0, square=False, detune=0.0):
    t = _t(dur)
    k = np.linspace(0.0, 1.0, t.size, dtype=np.float32)
    freq = f0 * (f1 / f0) ** k
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    wave = np.sin(phase)
    if square:
        wave = np.sign(wave) * 0.6 + wave * 0.4
    if detune:
        wave = wave * 0.7 + np.sin(phase * (1.0 + detune)) * 0.3
    return wave * _decay(t, decay)


def _noise(dur, decay=18.0, smooth=1):
    t = _t(dur)
    rng = np.random.default_rng(7)
    n = rng.uniform(-1.0, 1.0, t.size).astype(np.float32)
    if smooth > 1:                      # cheap low-pass = running mean
        n = np.convolve(n, np.ones(smooth, np.float32) / smooth, mode="same")
    return n * _decay(t, decay)


def _mix(*waves):
    """Sum layers of different lengths by padding to the longest."""
    n = max(w.size for w in waves)
    out = np.zeros(n, np.float32)
    for w in waves:
        out[:w.size] += w
    return out


def _chord(freqs, dur, decay=5.0):
    t = _t(dur)
    out = np.zeros(t.size, np.float32)
    for f in freqs:
        out += np.sin(2 * np.pi * f * t)
    return out / len(freqs) * _decay(t, decay)


def _build_bank():
    bank = {
        # a dry, short zap so a full magazine does not turn into mush
        "shoot": _mix(_sweep(1150, 380, 0.085, decay=34, square=True) * 0.55,
                      _noise(0.03, decay=60) * 0.25),
        "hit": _mix(_noise(0.06, decay=45, smooth=3) * 0.8,
                    _sweep(520, 200, 0.06, decay=40) * 0.3),
        "hurt": _sweep(190, 70, 0.24, decay=13, square=True) * 0.9,
        "kill": _sweep(720, 150, 0.38, decay=8, detune=0.01) * 0.85,
        "super": _sweep(220, 1250, 0.42, decay=4.5, square=True, detune=0.007) * 0.8,
        "spawn": _sweep(300, 940, 0.20, decay=11) * 0.6,
        "win": _chord([523, 659, 784], 0.85, decay=3.2) * 0.9,
        "lose": _chord([330, 262, 196], 0.95, decay=3.0) * 0.9,
    }
    out = {}
    for name, wave in bank.items():
        peak = float(np.max(np.abs(wave))) or 1.0
        out[name] = (wave / peak * 0.85).astype(np.float32)
    return out


# --------------------------------------------------------------------- mixer

class Audio:
    def __init__(self, master=0.5):
        self.master = master
        self.muted = False
        self.enabled = False
        self._proc = None
        self._fd = None
        self._voices = []
        self._backlog = np.zeros(0, np.float32)
        self._frac = 0.0
        self.bank = _build_bank()
        self._open()

    @property
    def status(self):
        if not self.enabled:
            return "off"
        return "muted" if self.muted else "on"

    def _open(self):
        devnull = subprocess.DEVNULL
        for cmd in PLAYERS:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                        stdout=devnull, stderr=devnull)
            except (OSError, ValueError):
                continue
            if proc.poll() is not None:
                continue
            self._proc = proc
            self._fd = proc.stdin.fileno()
            os.set_blocking(self._fd, False)
            self.enabled = True
            return

    def play(self, name, gain=1.0):
        if not self.enabled or self.muted or gain <= 0.01:
            return
        wave = self.bank.get(name)
        if wave is None:
            return
        if len(self._voices) >= MAX_VOICES:
            self._voices.pop(0)
        self._voices.append([wave, 0, float(gain)])

    def pump(self, dt):
        """Mix one frame worth of audio and hand it to the player."""
        if not self.enabled:
            return
        exact = dt * RATE + self._frac
        n = int(exact)
        self._frac = exact - n
        if n <= 0:
            return
        buf = np.zeros(n, np.float32)
        if self._voices:
            alive = []
            for voice in self._voices:
                wave, pos, gain = voice
                chunk = wave[pos:pos + n]
                if chunk.size:
                    buf[:chunk.size] += chunk * gain
                voice[1] = pos + n
                if voice[1] < wave.size:
                    alive.append(voice)
            self._voices = alive
        if self._backlog.size:
            buf = np.concatenate((self._backlog, buf))
            self._backlog = np.zeros(0, np.float32)
        if self.muted:
            buf[:] = 0.0
        # tanh soft-limits instead of hard clipping, so a burst of overlapping
        # effects saturates smoothly rather than crackling
        pcm = np.tanh(buf * self.master)
        data = (pcm * 32767.0).astype("<i2").tobytes()
        try:
            written = os.write(self._fd, data)
        except BlockingIOError:
            written = 0
        except (BrokenPipeError, OSError):
            self.enabled = False
            return
        if written < len(data):
            left = np.frombuffer(data[written:], dtype="<i2").astype(np.float32) / 32767.0
            self._backlog = left[-MAX_BACKLOG:] if left.size > MAX_BACKLOG else left

    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self._voices.clear()
        return self.muted

    def close(self):
        self.enabled = False
        if self._proc is None:
            return
        try:
            os.set_blocking(self._fd, True)
            self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=0.5)
        except Exception:
            self._proc.kill()


class Silent:
    """Stand-in used when the audio module or a player is unavailable."""

    enabled = False
    muted = True
    status = "off"

    def play(self, *_a, **_k):
        pass

    def pump(self, _dt):
        pass

    def toggle_mute(self):
        return True

    def close(self):
        pass
