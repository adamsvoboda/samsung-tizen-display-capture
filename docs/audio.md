# Audio quality

The output defaults to AAC-LC, 48 kHz stereo, 192 kbps. A file's sample rate and bitrate describe its format; they do not prove that the source contains frequencies across that range.

Existing direct monitor captures, OBS recordings, and saved raw PCM all showed a sharp drop in energy above approximately 8 kHz. The raw PCM result puts the limitation before AAC encoding. An upstream 16 kHz stage or low-pass filter would be consistent with this, but the precise cause has not been established.

The OBS recordings examined used AAC at 160 kbps, adding a second encode to the incoming roughly 192 kbps AAC stream. That may add compression loss, but it does not explain the cutoff already present in raw monitor audio. There was no sustained clipping, forced mono, or gross channel polarity problem in the inspected recordings.

The release pipeline explicitly requests 48 kHz stereo immediately after `pulsesrc`, before resampling. It produced decodable AAC on the tested G80SD, but **a full-band audio improvement has not been verified**. The source may already have removed high frequencies.

For now:

- Use OBS at 48 kHz and avoid duplicate Desktop Audio/Media Source capture or monitoring loops.
- `--audio-bitrate 256` reduces a compression constraint but cannot restore missing treble.
- `--mute` disables the monitor audio branch if you have a separate, better audio source.
- To isolate the remaining issue, compare a known full-band source with a direct capture and inspect the actual source sample specification and negotiated format. Save original audio for comparison; a movie's unknown audio master is not a controlled reference.
