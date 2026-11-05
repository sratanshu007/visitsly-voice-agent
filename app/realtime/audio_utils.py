import io
import struct
import numpy as np


# Precomputed ITU-T G.711 Mu-law to Linear PCM16 Table (256 entries)
def _build_mulaw_to_linear16_table() -> list[int]:
    table = []
    for b in range(256):
        inv = (~b) & 0xFF
        sign = inv & 0x80
        exponent = (inv >> 4) & 0x07
        mantissa = inv & 0x0F
        sample = ((mantissa << 3) + 0x84) << exponent
        sample -= 0x84
        if sign == 0:
            sample = -sample
        # Clamp to 16-bit signed integer range
        sample = max(-32768, min(32767, sample))
        table.append(sample)
    return table


MULAW_TO_LINEAR16 = _build_mulaw_to_linear16_table()
_MULAW_DECODE_STRUCT = struct.Struct("<" + "h" * 256)


def mulaw_to_linear16(mulaw_bytes: bytes) -> bytes:
    """Decodes 8-bit G.711 mu-law audio to 16-bit linear PCM."""
    if not mulaw_bytes:
        return b""
    # Using numpy for vectorized lookup if array is large, or list comprehension
    try:
        arr = np.frombuffer(mulaw_bytes, dtype=np.uint8)
        table_arr = np.array(MULAW_TO_LINEAR16, dtype=np.int16)
        pcm_samples = table_arr[arr]
        return pcm_samples.tobytes()
    except Exception:
        # Pure Python fallback
        return b"".join(struct.pack("<h", MULAW_TO_LINEAR16[b]) for b in mulaw_bytes)


# Precomputed Linear PCM16 to G.711 Mu-law
# Bias = 0x84, Max = 32767
def _linear16_sample_to_mulaw(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0x00
    if sample < 0:
        sample = -sample
    sample = min(sample, 32767)
    sample += 0x84

    # Determine exponent (segment)
    exponent = 7
    for exp, threshold in enumerate((0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF, 0x3FFF, 0x7FFF)):
        if sample <= threshold:
            exponent = exp
            break

    mantissa = (sample >> (exponent + 3)) & 0x0F
    mulaw = ~(sign | (exponent << 4) | mantissa) & 0xFF
    return mulaw


_LINEAR_TO_MULAW_TABLE = [_linear16_sample_to_mulaw(s) for s in range(-32768, 32768)]


def linear16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Encodes 16-bit linear PCM audio to 8-bit G.711 mu-law."""
    if not pcm_bytes:
        return b""
    # Ensure byte length is even
    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[:-1]

    try:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        # Shift index by 32768 to map [-32768..32767] -> [0..65535]
        indices = (samples.astype(np.int32) + 32768).clip(0, 65535)
        table = np.array(_LINEAR_TO_MULAW_TABLE, dtype=np.uint8)
        return table[indices].tobytes()
    except Exception:
        # Fallback
        num_samples = len(pcm_bytes) // 2
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
        return bytes(_LINEAR_TO_MULAW_TABLE[s + 32768] for s in samples)


def resample_pcm(pcm_bytes: bytes, in_rate: int, out_rate: int = 8000) -> bytes:
    """Resamples 16-bit linear mono PCM from in_rate to out_rate."""
    if in_rate == out_rate or not pcm_bytes:
        return pcm_bytes

    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[:-1]

    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    if len(samples) == 0:
        return b""

    # Linear interpolation
    duration = len(samples) / float(in_rate)
    target_num_samples = int(duration * out_rate)
    if target_num_samples == 0:
        return b""

    orig_indices = np.linspace(0, len(samples) - 1, target_num_samples)
    resampled = np.interp(orig_indices, np.arange(len(samples)), samples).astype(np.int16)
    return resampled.tobytes()


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 8000, channels: int = 1) -> bytes:
    """Wraps raw 16-bit PCM bytes into a standard RIFF WAV container."""
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm_bytes)

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # Subchunk1Size (16 for PCM)
        1,   # AudioFormat (1 for PCM)
        channels,
        sample_rate,
        byte_rate,
        block_align,
        16,  # BitsPerSample
        b"data",
        data_size,
    )
    return header + pcm_bytes


def mulaw_to_wav(mulaw_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Converts 8kHz mu-law audio to clean 16kHz WAV format for Whisper STT."""
    pcm = mulaw_to_linear16(mulaw_bytes)
    if sample_rate != 8000:
        pcm = resample_pcm(pcm, in_rate=8000, out_rate=sample_rate)
    return pcm_to_wav(pcm, sample_rate=sample_rate, channels=1)


def split_into_chunks(audio_data: bytes, chunk_size: int = 160) -> list[bytes]:
    """
    Splits audio bytes into fixed-size chunks.
    160 bytes of 8000Hz 8-bit mu-law = exactly 20 milliseconds of audio frame.
    """
    return [audio_data[i:i + chunk_size] for i in range(0, len(audio_data), chunk_size)]


def compute_audio_energy(mulaw_bytes: bytes) -> float:
    """Calculates RMS energy of mu-law audio chunk. Returns value typically between 0 and 32767."""
    if not mulaw_bytes:
        return 0.0
    try:
        pcm = mulaw_to_linear16(mulaw_bytes)
        samples = np.frombuffer(pcm, dtype=np.int16)
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
    except Exception:
        return 0.0


