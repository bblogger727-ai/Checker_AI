"""
Video to English SRT Subtitle Generator - SPLIT MODE
Extracts audio from video, splits it into multiple parts at silent moments,
transcribes each part separately, and merges them with correct timestamps.
This ensures complete coverage and better reliability for longer videos.
"""

import os
import sys
import argparse
from pathlib import Path
import subprocess
import json
from typing import List, Tuple, Dict, Optional, Any
import tempfile
import re

# Fix encoding for Windows console to handle emoji and Unicode characters
if sys.platform == "win32":
    try:
        # Reconfigure stdout and stderr to use UTF-8 encoding
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        # If reconfiguration fails, continue anyway
        pass

# Fix UTF-8 encoding for Windows console to handle emojis
if sys.platform == 'win32':
    try:
        import codecs
        if sys.stdout.encoding != 'utf-8':
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except Exception:
        # If that fails, try a simpler approach
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass  # If all fails, continue without UTF-8 (emojis might not display)

def install_package(package_name: str) -> bool:
    """
    Attempt to install a package using pip.
    
    Args:
        package_name: Name of the package to install
    
    Returns:
        True if installation succeeded, False otherwise
    """
    print(f"\n📦 Package '{package_name}' not found. Attempting to install...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"   ✓ Successfully installed '{package_name}'")
        return True
    except subprocess.CalledProcessError:
        print(f"   ✗ Failed to install '{package_name}'")
        return False


# Try importing OpenAI for API mode
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    # Try to install it automatically
    if install_package("openai"):
        try:
            from openai import OpenAI
            OPENAI_AVAILABLE = True
        except ImportError:
            pass

# Try importing Whisper for local mode
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

# Try importing pydub for audio splitting
try:
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# ============================================================================
# PASTE YOUR OPENAI API KEY HERE (between the quotes)
# ============================================================================
DEFAULT_API_KEY = os.getenv("OPENAI_API_KEY", "")
# ============================================================================


class VideoToSRTConverter:
    """Converts video with Hindi audio to English SRT subtitles with smart audio splitting."""
    
    def __init__(self, api_key: str = None, use_local: bool = False, model_size: str = "base", num_splits: int = 3):
        """
        Initialize the converter.
        
        Args:
            api_key: OpenAI API key (required if use_local=False)
            use_local: If True, use local Whisper instead of API
            model_size: Whisper model size for local mode
            num_splits: Number of parts to split audio into (default: 3, auto-adjusted based on video length)
        """
        self.use_local = use_local
        self.model_size = model_size
        self.num_splits = num_splits
        self.initial_num_splits = num_splits  # Store original request
        self._check_ffmpeg()
        
        if use_local:
            if not WHISPER_AVAILABLE:
                raise RuntimeError(
                    "Local Whisper not available. Install with: pip install openai-whisper\n"
                    "Note: For GPU acceleration, also install: pip install torch torchvision torchaudio"
                )
            self._init_local_whisper()
        else:
            if not OPENAI_AVAILABLE:
                raise RuntimeError(
                    "OpenAI package not installed. Run: pip install openai\n"
                    "Or use local mode: use_local=True"
                )
            self.api_key = api_key or os.getenv("OPENAI_API_KEY") or DEFAULT_API_KEY
            if not self.api_key or self.api_key == "PASTE_YOUR_NEW_API_KEY_HERE":
                raise ValueError(
                    "OpenAI API key not provided. Either:\n"
                    "1. Paste your API key at the top of this file (DEFAULT_API_KEY), OR\n"
                    "2. Set OPENAI_API_KEY environment variable, OR\n"
                    "3. Use local mode: use_local=True (free, no API key needed)"
                )
            self.client = OpenAI(api_key=self.api_key)
    
    def _init_local_whisper(self):
        """Initialize local Whisper model."""
        print(f"\n🤖 Initializing local Whisper model: {self.model_size}")
        print("   This may take a moment on first run (downloading model)...")
        
        try:
            self.whisper_model = whisper.load_model(self.model_size)
            print(f"   ✓ Model loaded successfully!")
            
            try:
                import torch
                if torch.cuda.is_available():
                    print(f"   ✓ GPU acceleration available (CUDA)")
                else:
                    print(f"   ℹ️  Using CPU (will be slower, but works)")
            except ImportError:
                print(f"   ℹ️  PyTorch not detected - using CPU")
        except Exception as e:
            raise RuntimeError(f"Failed to load Whisper model: {str(e)}")
    
    def _check_ffmpeg(self):
        """Check if FFmpeg is installed."""
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError(
                "FFmpeg is not installed or not in PATH. Please install FFmpeg:\n"
                "Windows: Download from https://ffmpeg.org/download.html\n"
                "Or use: winget install ffmpeg"
            )
    
    def get_video_duration(self, video_path: str) -> float:
        """Get the duration of a video or audio file in seconds."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                text=True
            )
            duration = float(result.stdout.strip())
            return duration
        except (subprocess.CalledProcessError, ValueError) as e:
            raise RuntimeError(f"Failed to get duration for {video_path}: {str(e)}")
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in seconds to human-readable string."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"
        else:
            return f"{minutes:02d}:{secs:05.2f}"
    
    def find_split_points_ffmpeg(self, audio_path: str, num_splits: int) -> List[float]:
        """
        Find optimal split points in audio using FFmpeg's silence detection.
        Splits audio into num_splits parts at silent moments.
        
        Args:
            audio_path: Path to audio file
            num_splits: Number of parts to split into
        
        Returns:
            List of split times in seconds (length will be num_splits - 1)
        """
        print(f"\n🔍 Finding optimal split points using silence detection...")
        print(f"   Target: {num_splits} parts")
        
        duration = self.get_video_duration(audio_path)
        ideal_split_interval = duration / num_splits
        
        print(f"   Audio duration: {self._format_duration(duration)}")
        print(f"   Ideal split interval: ~{self._format_duration(ideal_split_interval)}")
        
        # Use FFmpeg to detect silence
        # silencedetect filter finds silent portions
        cmd = [
            "ffmpeg",
            "-i", audio_path,
            "-af", "silencedetect=noise=-30dB:d=0.5",  # Detect silence quieter than -30dB lasting 0.5s+
            "-f", "null",
            "-"
        ]
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Parse silence detection output from stderr
            silence_starts = []
            silence_ends = []
            
            for line in result.stderr.split('\n'):
                if 'silence_start' in line:
                    match = re.search(r'silence_start: ([\d.]+)', line)
                    if match:
                        silence_starts.append(float(match.group(1)))
                elif 'silence_end' in line:
                    match = re.search(r'silence_end: ([\d.]+)', line)
                    if match:
                        silence_ends.append(float(match.group(1)))
            
            # Create silence intervals (middle of each silence period)
            silence_midpoints = []
            for start, end in zip(silence_starts, silence_ends):
                midpoint = (start + end) / 2
                silence_midpoints.append(midpoint)
            
            print(f"   Found {len(silence_midpoints)} silent moments")
            
            if len(silence_midpoints) < num_splits - 1:
                print(f"   ⚠ Not enough silent moments found for {num_splits} splits")
                print(f"   Using equal time intervals instead...")
                split_points = [ideal_split_interval * i for i in range(1, num_splits)]
            else:
                # Find split points closest to ideal intervals
                split_points = []
                for i in range(1, num_splits):
                    target_time = ideal_split_interval * i
                    # Find closest silence to this target
                    closest = min(silence_midpoints, key=lambda x: abs(x - target_time))
                    split_points.append(closest)
                    # Remove used silence point
                    silence_midpoints.remove(closest)
            
            print(f"   ✓ Split points selected:")
            for i, point in enumerate(split_points, 1):
                print(f"      Split {i}: {self._format_duration(point)}")
            
            return sorted(split_points)
            
        except Exception as e:
            print(f"   ⚠ Error detecting silence: {str(e)}")
            print(f"   Falling back to equal time intervals...")
            split_points = [ideal_split_interval * i for i in range(1, num_splits)]
            return split_points
    
    def split_audio_ffmpeg(self, audio_path: str, split_points: List[float], output_dir: str) -> List[Tuple[str, float]]:
        """
        Split audio file at specified points using FFmpeg.
        
        Args:
            audio_path: Path to audio file
            split_points: List of split times in seconds
            output_dir: Directory to save split audio files
        
        Returns:
            List of tuples (file_path, start_time_offset)
        """
        print(f"\n✂️  Splitting audio into {len(split_points) + 1} parts...")
        
        duration = self.get_video_duration(audio_path)
        split_files = []
        
        # Add start and end boundaries
        boundaries = [0.0] + split_points + [duration]
        
        for i in range(len(boundaries) - 1):
            start_time = boundaries[i]
            end_time = boundaries[i + 1]
            segment_duration = end_time - start_time
            
            output_file = os.path.join(output_dir, f"part_{i+1}.mp3")
            
            print(f"   Part {i+1}: {self._format_duration(start_time)} → {self._format_duration(end_time)} ({self._format_duration(segment_duration)})")
            
            # Use FFmpeg to extract segment
            cmd = [
                "ffmpeg",
                "-i", audio_path,
                "-ss", str(start_time),
                "-to", str(end_time),
                "-acodec", "copy",  # Copy codec for speed
                "-y",
                output_file
            ]
            
            subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            
            file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"      ✓ Created: {output_file} ({file_size_mb:.2f} MB)")
            
            split_files.append((output_file, start_time))
        
        print(f"   ✓ Audio split completed!")
        return split_files
    
    def extract_audio(self, video_path: str, output_audio_path: str = None) -> str:
        """Extract audio from video file."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        if output_audio_path is None:
            temp_dir = tempfile.gettempdir()
            video_name = Path(video_path).stem
            output_audio_path = os.path.join(temp_dir, f"{video_name}_audio.mp3")
        
        print(f"\n🎬 Extracting audio from video: {video_path}")
        print(f"   Output audio: {output_audio_path}")
        
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",
            "-map", "0:a:0",
            "-acodec", "libmp3lame",
            "-ar", "44100",
            "-ac", "2",
            "-b:a", "192k",
            "-y",
            output_audio_path
        ]
        
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                text=True
            )
            
            if not os.path.exists(output_audio_path):
                raise RuntimeError("Audio file was not created by FFmpeg")
            
            file_size = os.path.getsize(output_audio_path)
            if file_size == 0:
                raise RuntimeError("Audio file is empty (0 bytes)")
            
            print(f"   ✓ Audio extraction completed successfully")
            file_size_mb = file_size / (1024*1024)
            print(f"   File size: {file_size_mb:.2f} MB")
            
            return output_audio_path
            
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"FFmpeg error during audio extraction:\n{e.stderr}")
    
    def detect_silence_at_start(self, audio_path: str, add_buffer: float = 3.0, min_silence_for_buffer: float = 3.0) -> float:
        """
        Detect how much silence exists at the beginning of the audio.
        If silence > min_silence_for_buffer, adds extra buffer to skip intro music.
        
        Args:
            audio_path: Path to audio file
            add_buffer: Extra seconds to add if significant silence detected (default: 3.0)
            min_silence_for_buffer: Minimum silence duration to trigger buffer (default: 3.0)
        
        Returns:
            Adjusted start time in seconds (includes buffer if applicable)
        """
        print(f"\n🔍 Detecting silence at beginning of audio...")
        
        cmd = [
            "ffmpeg",
            "-i", audio_path,
            "-af", "silencedetect=noise=-30dB:d=0.3",
            "-f", "null",
            "-"
        ]
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Parse all silence events
            silence_starts = []
            silence_ends = []
            
            for line in result.stderr.split('\n'):
                if 'silence_start' in line:
                    match = re.search(r'silence_start: ([\d.]+)', line)
                    if match:
                        silence_starts.append(float(match.group(1)))
                elif 'silence_end' in line:
                    match = re.search(r'silence_end: ([\d.]+)', line)
                    if match:
                        silence_ends.append(float(match.group(1)))
            
            # Check if there's silence at the very beginning
            # Silence at start means silence_start should be at or very near 0 (within 0.5 seconds)
            if silence_starts and silence_starts[0] <= 0.5:
                # There IS silence at the start
                # Find the corresponding silence_end
                if silence_ends:
                    silence_duration = silence_ends[0]
                    
                    # Only consider meaningful silence (> 0.5 seconds)
                    if silence_duration > 0.5:
                            print(f"   ✓ Detected {silence_duration:.2f}s of silence at start")
                            
                            # If silence > threshold, add buffer to skip intro music
                            if silence_duration > min_silence_for_buffer:
                                adjusted_start = silence_duration + add_buffer
                                print(f"   🎵 Silence > {min_silence_for_buffer}s detected - adding {add_buffer}s buffer for intro music")
                                print(f"   📍 Adjusted start time: {adjusted_start:.2f}s (was {silence_duration:.2f}s)")
                                return adjusted_start
                            else:
                                return silence_duration
            
            print(f"   ✓ No significant silence at start (audio begins immediately)")
            return 0.0
            
        except Exception as e:
            print(f"   ⚠ Could not detect silence: {str(e)}")
            return 0.0
    
    def transcribe_audio_part(
        self, 
        audio_path: str,
        part_number: int,
        time_offset: float,
        source_language: str = "hi",
        is_first_part: bool = False
    ) -> List[dict]:
        """
        Transcribe a single audio part and adjust timestamps.
        
        Args:
            audio_path: Path to audio part file
            part_number: Part number (for display)
            time_offset: Time offset in seconds to add to all timestamps
            source_language: Source language code
            is_first_part: If True, will detect and correct silence at start
        
        Returns:
            List of segment dictionaries with adjusted timestamps
        """
        print(f"\n🗣️  Transcribing Part {part_number}...")
        print(f"   File: {audio_path}")
        print(f"   Time offset: {self._format_duration(time_offset)}")
        
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        print(f"   Size: {file_size_mb:.2f} MB")
        
        # Detect silence at start if this is the first part
        silence_at_start = 0.0
        if is_first_part:
            silence_at_start = self.detect_silence_at_start(audio_path)
        
        try:
            if self.use_local:
                result = self.whisper_model.transcribe(
                    audio_path,
                    language=source_language,
                    task="translate",
                    verbose=False
                )
                segments_raw = result.get('segments', [])
            else:
                with open(audio_path, "rb") as audio_file:
                    translation = self.client.audio.translations.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="verbose_json"
                    )
                segments_raw = translation.segments
            
            # Convert to standard format and adjust timestamps
            segments = []
            for i, seg in enumerate(segments_raw):
                if self.use_local:
                    start = seg['start'] + time_offset
                    end = seg['end'] + time_offset
                    text = seg['text'].strip()
                else:
                    start = seg.start + time_offset
                    end = seg.end + time_offset
                    text = seg.text.strip()
                
                # Adjust ONLY the first segment if silence was detected
                if is_first_part and i == 0 and silence_at_start > 0.5:
                    print(f"   🔧 Adjusting first segment: moving start from {self._format_duration(start)} to {self._format_duration(start + silence_at_start)}")
                    start = start + silence_at_start
                    # Make sure end doesn't become before start
                    if end <= start:
                        end = start + 1.0
                
                segments.append({
                    'start': start,
                    'end': end,
                    'text': text
                })
            
            print(f"   ✓ Part {part_number} transcribed: {len(segments)} segments")
            if segments:
                print(f"   Time range: {self._format_duration(segments[0]['start'])} → {self._format_duration(segments[-1]['end'])}")
            
            return segments
            
        except Exception as e:
            raise RuntimeError(f"Error transcribing part {part_number}: {str(e)}")
    
    def _transcribe_in_small_chunks(
        self,
        audio_path: str,
        start_time: float,
        end_time: float,
        source_language: str,
        temp_dir: str,
        chunk_size: float = 5.0
    ) -> List[dict]:
        """
        Split the missing portion into small chunks and transcribe each one.
        
        Args:
            audio_path: Path to audio file
            start_time: Start time of missing portion
            end_time: End time of missing portion
            source_language: Source language code
            temp_dir: Temporary directory for chunk files
            chunk_size: Size of each chunk in seconds (default: 5.0)
        
        Returns:
            List of segments from chunk transcription
        """
        duration = end_time - start_time
        num_chunks = int(duration / chunk_size) + (1 if duration % chunk_size > 0 else 0)
        
        print(f"      Splitting {self._format_duration(duration)} into {num_chunks} chunks of ~{chunk_size}s each...")
        
        all_chunk_segments = []
        
        for i in range(num_chunks):
            chunk_start = start_time + (i * chunk_size)
            chunk_end = min(start_time + ((i + 1) * chunk_size), end_time)
            
            # Add small overlap (0.5s) with previous chunk to maintain context
            overlap = 0.5 if i > 0 else 0
            extract_start = max(start_time, chunk_start - overlap)
            
            chunk_file = os.path.join(temp_dir, f"chunk_{i+1}.mp3")
            
            # Extract chunk
            cmd = [
                "ffmpeg",
                "-i", audio_path,
                "-ss", str(extract_start),
                "-to", str(chunk_end),
                "-acodec", "libmp3lame",
                "-y",
                chunk_file
            ]
            
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                
                # Transcribe chunk
                print(f"      Chunk {i+1}/{num_chunks}: {self._format_duration(chunk_start)} → {self._format_duration(chunk_end)}", end="")
                
                if self.use_local:
                    result = self.whisper_model.transcribe(
                        chunk_file,
                        language=source_language,
                        task="translate",
                        verbose=False
                    )
                    chunk_segments_raw = result.get('segments', [])
                else:
                    with open(chunk_file, "rb") as audio_file:
                        translation = self.client.audio.translations.create(
                            model="whisper-1",
                            file=audio_file,
                            response_format="verbose_json"
                        )
                    chunk_segments_raw = translation.segments
                
                # Convert and adjust timestamps
                for seg in chunk_segments_raw:
                    if self.use_local:
                        seg_start = seg['start'] + extract_start
                        seg_end = seg['end'] + extract_start
                        text = seg['text'].strip()
                    else:
                        seg_start = seg.start + extract_start
                        seg_end = seg.end + extract_start
                        text = seg.text.strip()
                    
                    # Only add segments within the actual chunk range (not the overlap)
                    if seg_start >= chunk_start - 0.1 and text:  # Small tolerance
                        all_chunk_segments.append({
                            'start': max(chunk_start, seg_start),
                            'end': seg_end,
                            'text': text
                        })
                
                if chunk_segments_raw:
                    print(f" ✓ ({len([s for s in chunk_segments_raw if (s.get('text') if self.use_local else s.text).strip()])} segments)")
                else:
                    print(f" ✗ (no speech)")
                
            except Exception as e:
                print(f" ✗ Error: {str(e)}")
        
        return all_chunk_segments
    
    def fill_missing_end_segments(
        self,
        audio_path: str,
        segments: List[dict],
        video_duration: float,
        source_language: str = "hi"
    ) -> List[dict]:
        """
        Check if transcription ended early and fill missing segments at the end.
        
        Args:
            audio_path: Path to audio file
            segments: Existing segments
            video_duration: Total video duration
            source_language: Source language code
        
        Returns:
            Complete list of segments including any missing end portions
        """
        if not segments:
            return segments
        
        last_subtitle_time = segments[-1]['end']
        time_gap = video_duration - last_subtitle_time
        
        # If there's more than 5 seconds missing, re-transcribe that portion
        if time_gap > 5.0:
            print(f"\n⚠️  COVERAGE GAP DETECTED!")
            print(f"   Last subtitle ends at: {self._format_duration(last_subtitle_time)}")
            print(f"   Video ends at: {self._format_duration(video_duration)}")
            print(f"   Missing: {self._format_duration(time_gap)}")
            print(f"\n🔧 Re-transcribing final {self._format_duration(time_gap)} to ensure complete coverage...")
            
            # Create temp directory for the final segment
            temp_dir = tempfile.mkdtemp(prefix="audio_end_")
            
            try:
                # Extract the missing portion (with 5 second overlap to ensure continuity)
                overlap = 5.0
                start_time = max(0, last_subtitle_time - overlap)
                output_file = os.path.join(temp_dir, "final_segment.mp3")
                
                cmd = [
                    "ffmpeg",
                    "-i", audio_path,
                    "-ss", str(start_time),
                    "-to", str(video_duration),
                    "-acodec", "libmp3lame",
                    "-y",
                    output_file
                ]
                
                subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )
                
                print(f"   ✓ Extracted final segment: {self._format_duration(start_time)} → {self._format_duration(video_duration)}")
                
                # Transcribe this final portion
                file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
                print(f"   📝 Transcribing final segment ({file_size_mb:.2f} MB)...")
                
                if self.use_local:
                    result = self.whisper_model.transcribe(
                        output_file,
                        language=source_language,
                        task="translate",
                        verbose=False
                    )
                    new_segments_raw = result.get('segments', [])
                else:
                    with open(output_file, "rb") as audio_file:
                        translation = self.client.audio.translations.create(
                            model="whisper-1",
                            file=audio_file,
                            response_format="verbose_json"
                        )
                    new_segments_raw = translation.segments
                
                # Convert to standard format and adjust timestamps
                new_segments = []
                for seg in new_segments_raw:
                    if self.use_local:
                        seg_start = seg['start'] + start_time
                        seg_end = seg['end'] + start_time
                        text = seg['text'].strip()
                    else:
                        seg_start = seg.start + start_time
                        seg_end = seg.end + start_time
                        text = seg.text.strip()
                    
                    # Only add segments that end after the last existing subtitle
                    # This ensures we capture anything that extends beyond existing coverage
                    if seg_end > last_subtitle_time + 0.5:  # Add if it extends coverage
                        # Adjust start time if it overlaps to avoid duplication
                        if seg_start < last_subtitle_time:
                            seg_start = last_subtitle_time
                        
                        new_segments.append({
                            'start': seg_start,
                            'end': seg_end,
                            'text': text
                        })
                
                if new_segments:
                    print(f"   ✓ Found {len(new_segments)} additional segments")
                    new_end_time = new_segments[-1]['end']
                    print(f"   ✓ Extended coverage to: {self._format_duration(new_end_time)}")
                    segments.extend(new_segments)
                    
                    # Check if there's still a gap
                    remaining_gap = video_duration - new_end_time
                    if remaining_gap > 3.0:
                        print(f"   ⚠️  Still missing {self._format_duration(remaining_gap)} - likely silence or background music without speech")
                else:
                    print(f"   ⚠️  Whisper did not detect speech in the final {self._format_duration(time_gap)}")
                    
                    # Try one more time with a longer segment (starting earlier) for better context
                    if time_gap < 30.0 and last_subtitle_time > 30.0:
                        print(f"   🔄 Retrying with longer context (last 30 seconds)...")
                        try:
                            longer_start = max(0, video_duration - 30.0)
                            output_file_2 = os.path.join(temp_dir, "final_segment_long.mp3")
                            
                            cmd2 = [
                                "ffmpeg",
                                "-i", audio_path,
                                "-ss", str(longer_start),
                                "-to", str(video_duration),
                                "-acodec", "libmp3lame",
                                "-y",
                                output_file_2
                            ]
                            
                            subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                            
                            if self.use_local:
                                result2 = self.whisper_model.transcribe(output_file_2, language=source_language, task="translate", verbose=False)
                                retry_segments_raw = result2.get('segments', [])
                            else:
                                with open(output_file_2, "rb") as audio_file:
                                    translation2 = self.client.audio.translations.create(model="whisper-1", file=audio_file, response_format="verbose_json")
                                retry_segments_raw = translation2.segments
                            
                            retry_segments = []
                            for seg in retry_segments_raw:
                                if self.use_local:
                                    seg_start = seg['start'] + longer_start
                                    seg_end = seg['end'] + longer_start
                                    text = seg['text'].strip()
                                else:
                                    seg_start = seg.start + longer_start
                                    seg_end = seg.end + longer_start
                                    text = seg.text.strip()
                                
                                if seg_end > last_subtitle_time + 0.5:
                                    if seg_start < last_subtitle_time:
                                        seg_start = last_subtitle_time
                                    retry_segments.append({'start': seg_start, 'end': seg_end, 'text': text})
                            
                            if retry_segments:
                                print(f"   ✓ Retry successful! Found {len(retry_segments)} additional segments")
                                print(f"   ✓ Extended coverage to: {self._format_duration(retry_segments[-1]['end'])}")
                                segments.extend(retry_segments)
                            else:
                                print(f"   ℹ️  Retry also found no speech")
                                print(f"   🔧 Final attempt: Splitting missing portion into small chunks...")
                                
                                # Split the missing portion into 5-second chunks
                                chunk_segments = self._transcribe_in_small_chunks(
                                    audio_path, 
                                    last_subtitle_time, 
                                    video_duration, 
                                    source_language,
                                    temp_dir
                                )
                                
                                if chunk_segments:
                                    print(f"   ✓ Chunk transcription successful! Found {len(chunk_segments)} additional segments")
                                    print(f"   ✓ Extended coverage to: {self._format_duration(chunk_segments[-1]['end'])}")
                                    segments.extend(chunk_segments)
                                else:
                                    print(f"   ⚠️  Even chunk transcription found no speech")
                                    print(f"   💡 Recommendation: Manually verify the last {self._format_duration(time_gap)} of your video")
                        except Exception as e2:
                            print(f"   ⚠️  Retry failed: {str(e2)}")
                    else:
                        print(f"   ℹ️  This could mean:")
                        print(f"      - The audio contains only music/silence at the end")
                        print(f"      - The speech is too unclear for Whisper to transcribe")
                        print(f"      - Background noise is too high")
                        print(f"   💡 Recommendation: Manually verify the last {self._format_duration(time_gap)} of your video")
                
            except Exception as e:
                print(f"   ⚠️  Could not re-transcribe final segment: {str(e)}")
            finally:
                # Cleanup
                try:
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
        
        return segments
    
    def transcribe_and_translate_split(
        self, 
        audio_path: str,
        source_language: str = "hi"
    ) -> List[dict]:
        """
        Transcribe audio by splitting it into parts and merging results.
        
        Args:
            audio_path: Path to audio file
            source_language: Source language code
        
        Returns:
            List of all segments with correct timestamps
        """
        print("\n" + "="*70)
        
        # Adjust num_splits to ensure no segment is too short (minimum 60 seconds per segment)
        duration = self.get_video_duration(audio_path)
        min_segment_duration = 60.0  # Minimum 1 minute per segment
        max_splits_for_duration = max(1, int(duration / min_segment_duration))
        
        original_splits = self.num_splits
        self.num_splits = min(self.num_splits, max_splits_for_duration)
        
        if self.num_splits != original_splits:
            print(f"📊 Auto-adjusted splits: {original_splits} → {self.num_splits} (to ensure minimum {min_segment_duration}s per segment)")
        
        print(f"SPLIT-MODE TRANSCRIPTION ({self.num_splits} parts)")
        print("="*70)
        
        # Create temp directory for split files
        temp_dir = tempfile.mkdtemp(prefix="audio_split_")
        
        try:
            # Find optimal split points
            split_points = self.find_split_points_ffmpeg(audio_path, self.num_splits)
            
            # Split audio
            split_files = self.split_audio_ffmpeg(audio_path, split_points, temp_dir)
            
            # Transcribe each part
            all_segments = []
            for i, (part_file, time_offset) in enumerate(split_files, 1):
                part_segments = self.transcribe_audio_part(
                    part_file,
                    i,
                    time_offset,
                    source_language,
                    is_first_part=(i == 1)  # Only first part checks for silence at start
                )
                all_segments.extend(part_segments)
            
            print("\n" + "="*70)
            print("✅ ALL PARTS TRANSCRIBED")
            print("="*70)
            print(f"   Total segments: {len(all_segments)}")
            if all_segments:
                print(f"   Timeline: {self._format_duration(all_segments[0]['start'])} → {self._format_duration(all_segments[-1]['end'])}")
            
            return all_segments
            
        finally:
            # Cleanup temp files
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                print(f"   Cleaned up temporary split files")
            except:
                pass
    
    def split_long_segments(self, segments: List[dict], max_chars: int = 84, max_duration: float = 7.0) -> List[dict]:
        """
        Split long segments into smaller, readable chunks.
        
        Args:
            segments: Original segments
            max_chars: Maximum characters per subtitle (default: 84 = 2 lines of ~42 chars)
            max_duration: Maximum duration in seconds (default: 7.0)
        
        Returns:
            List of segments split into readable chunks
        """
        print(f"\n✂️  Breaking long subtitles into readable chunks...")
        print(f"   Max characters per subtitle: {max_chars}")
        print(f"   Max duration per subtitle: {max_duration}s")
        
        new_segments = []
        split_count = 0
        
        for segment in segments:
            text = segment['text'].strip()
            start = segment['start']
            end = segment['end']
            duration = end - start
            
            # Check if segment needs splitting
            if len(text) <= max_chars and duration <= max_duration:
                new_segments.append(segment)
                continue
            
            # Need to split this segment
            split_count += 1
            
            # Split text at natural break points
            chunks = self._split_text_smartly(text, max_chars)
            
            if len(chunks) == 1:
                # Couldn't split text, keep as is
                new_segments.append(segment)
                continue
            
            # Distribute time across chunks proportionally based on WORD COUNT
            chunk_word_counts = [len(chunk.split()) for chunk in chunks]
            total_words = sum(chunk_word_counts)
            current_time = start
            
            for i, chunk in enumerate(chunks):
                # Calculate duration for this chunk based on word count proportion
                chunk_word_count = chunk_word_counts[i]
                chunk_proportion = chunk_word_count / total_words if total_words > 0 else 1.0 / len(chunks)
                chunk_duration = duration * chunk_proportion
                
                # Ensure minimum duration of 1 second
                chunk_duration = max(1.0, chunk_duration)
                
                chunk_end = current_time + chunk_duration
                # Make sure we don't exceed original end time
                if i == len(chunks) - 1:
                    chunk_end = end
                
                new_segments.append({
                    'start': current_time,
                    'end': chunk_end,
                    'text': chunk.strip()
                })
                
                current_time = chunk_end
        
        print(f"   ✓ Split {split_count} long segments")
        print(f"   Before: {len(segments)} segments → After: {len(new_segments)} segments")
        
        return new_segments
    
    def _split_text_smartly(self, text: str, max_chars: int) -> List[str]:
        """
        Split text at natural break points (punctuation, conjunctions).
        
        Args:
            text: Text to split
            max_chars: Maximum characters per chunk
        
        Returns:
            List of text chunks
        """
        if len(text) <= max_chars:
            return [text]
        
        # Try to split at sentence boundaries first (. ! ?)
        sentences = re.split(r'([.!?]+\s+)', text)
        
        # Rejoin punctuation with sentences
        clean_sentences = []
        for i in range(0, len(sentences) - 1, 2):
            if i + 1 < len(sentences):
                clean_sentences.append(sentences[i] + sentences[i + 1])
            else:
                clean_sentences.append(sentences[i])
        if len(sentences) % 2 == 1:
            clean_sentences.append(sentences[-1])
        
        # Group sentences into chunks
        chunks = []
        current_chunk = ""
        
        for sentence in clean_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # If adding this sentence exceeds max_chars, start new chunk
            if current_chunk and len(current_chunk) + len(sentence) + 1 > max_chars:
                chunks.append(current_chunk)
                current_chunk = sentence
            else:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # If we still have chunks that are too long, split by commas
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= max_chars:
                final_chunks.append(chunk)
            else:
                # Split by commas
                parts = chunk.split(', ')
                current_part = ""
                for part in parts:
                    if current_part and len(current_part) + len(part) + 2 > max_chars:
                        final_chunks.append(current_part)
                        current_part = part
                    else:
                        if current_part:
                            current_part += ", " + part
                        else:
                            current_part = part
                if current_part:
                    final_chunks.append(current_part)
        
        # Last resort: if still too long, split by words
        result_chunks = []
        for chunk in final_chunks:
            if len(chunk) <= max_chars:
                result_chunks.append(chunk)
            else:
                words = chunk.split()
                current = ""
                for word in words:
                    if current and len(current) + len(word) + 1 > max_chars:
                        result_chunks.append(current)
                        current = word
                    else:
                        if current:
                            current += " " + word
                        else:
                            current = word
                if current:
                    result_chunks.append(current)
        
        return result_chunks if result_chunks else [text]
    
    def segments_to_srt(self, segments: List[dict]) -> str:
        """Convert segments to SRT format."""
        if not segments:
            raise ValueError("No segments provided for SRT generation")
        
        # First, split long segments into readable chunks
        segments = self.split_long_segments(segments)
        
        srt_content = []
        
        print(f"\n📝 Generating SRT file from {len(segments)} segments...")
        
        for i, segment in enumerate(segments, start=1):
            start = segment['start']
            end = segment['end']
            text = segment['text'].strip()
            
            if start < 0:
                start = 0
            if end <= start:
                end = start + 1.0
            
            start_time = self._format_timestamp(start)
            end_time = self._format_timestamp(end)
            
            srt_content.append(f"{i}")
            srt_content.append(f"{start_time} --> {end_time}")
            srt_content.append(text)
            srt_content.append("")
        
        print(f"   ✓ SRT generation completed")
        print(f"   Total subtitle entries: {len(segments)}")
        print(f"   Timeline: {self._format_duration(segments[0]['start'])} → {self._format_duration(segments[-1]['end'])}")
        
        return "\n".join(srt_content)
    
    def _format_timestamp(self, seconds: float) -> str:
        """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    
    def replace_words_in_srt(self, srt_content: str, replacements: Dict[str, str]) -> str:
        """
        Replace specific words throughout the entire SRT content.
        Case-insensitive replacement that preserves original capitalization pattern.
        
        Args:
            srt_content: Original SRT content
            replacements: Dictionary of {old_word: new_word}
        
        Returns:
            Modified SRT content with replacements applied
        """
        if not replacements:
            return srt_content
        
        print(f"\n🔄 Replacing words in subtitles...")
        
        modified_content = srt_content
        total_replacements = 0
        
        for old_word, new_word in replacements.items():
            # Create case-insensitive pattern that matches whole words
            pattern = re.compile(r'\b' + re.escape(old_word) + r'\b', re.IGNORECASE)
            
            # Count matches
            matches = pattern.findall(modified_content)
            count = len(matches)
            
            if count > 0:
                # Replace while preserving case pattern
                def replace_with_case(match):
                    matched_text = match.group(0)
                    # If original is all caps, make replacement all caps
                    if matched_text.isupper():
                        return new_word.upper()
                    # If original is title case, make replacement title case
                    elif matched_text[0].isupper():
                        return new_word.capitalize()
                    # Otherwise lowercase
                    else:
                        return new_word.lower()
                
                modified_content = pattern.sub(replace_with_case, modified_content)
                total_replacements += count
                print(f"   ✓ Replaced '{old_word}' → '{new_word}' ({count} occurrences)")
        
        if total_replacements > 0:
            print(f"   ✓ Total replacements: {total_replacements}")
        else:
            print(f"   ℹ️  No words found to replace")
        
        return modified_content
    
    def convert_video_to_srt(
        self,
        video_path: str,
        output_srt_path: str = None,
        keep_audio: bool = False,
        source_language: str = "hi",
        word_replacements: Dict[str, str] = None
    ) -> Tuple[str, str]:
        """
        Complete pipeline with audio splitting for complete coverage.
        
        Args:
            video_path: Path to input video file
            output_srt_path: Path for output SRT file
            keep_audio: Whether to keep the extracted audio file
            source_language: Source language code
            word_replacements: Dictionary of words to replace {old: new} (e.g., {"pooja": "Rucha"})
        
        Returns:
            Tuple of (srt_path, audio_path)
        """
        print("="*70)
        print("VIDEO TO ENGLISH SRT CONVERTER - SPLIT MODE")
        print("="*70)
        
        video_path_obj = Path(video_path)
        if output_srt_path is None:
            output_srt_path = video_path_obj.with_suffix('.srt')
        
        original_video_duration = self.get_video_duration(video_path)
        print(f"\n📹 Input video: {video_path}")
        print(f"   Video duration: {self._format_duration(original_video_duration)}")
        
        temp_audio = None
        try:
            # Extract audio
            audio_path = self.extract_audio(video_path)
            temp_audio = audio_path
            
            # Transcribe with splitting
            segments = self.transcribe_and_translate_split(audio_path, source_language)
            
            # Check for missing audio at the end and re-transcribe if needed
            segments = self.fill_missing_end_segments(audio_path, segments, original_video_duration, source_language)
            
            # Generate SRT
            srt_content = self.segments_to_srt(segments)
            
            # ALWAYS apply default word replacements (hardcoded)
            default_replacements = {"pooja": "Rucha"}
            srt_content = self.replace_words_in_srt(srt_content, default_replacements)
            
            # Apply additional word replacements if specified
            if word_replacements:
                srt_content = self.replace_words_in_srt(srt_content, word_replacements)
            
            # Save SRT file
            with open(output_srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            # Final summary
            print("\n" + "="*70)
            print("✅ CONVERSION SUCCESSFUL!")
            print("="*70)
            
            last_subtitle_time = segments[-1]['end'] if segments else 0
            coverage_percent = (last_subtitle_time / original_video_duration) * 100 if original_video_duration > 0 else 0
            
            print(f"\n📊 VERIFICATION SUMMARY:")
            print(f"   ✓ Video duration:        {self._format_duration(original_video_duration)}")
            print(f"   ✓ Subtitles end at:      {self._format_duration(last_subtitle_time)}")
            print(f"   ✓ Coverage:              {coverage_percent:.1f}%")
            print(f"   ✓ Total subtitle count:  {len(segments)}")
            print(f"   ✓ SRT file created:      {output_srt_path}")
            
            if coverage_percent < 95:
                print(f"\n   ℹ️  Coverage is {coverage_percent:.1f}%")
                if coverage_percent < 80:
                    print(f"      ⚠ This is lower than expected. There may be extended silence at the end.")
                else:
                    print(f"      This is normal if there's silence at the end of the video")
            else:
                print(f"\n   ✓ Excellent coverage! Subtitles span the entire video.")
            
            print(f"\n🎯 SPLIT-MODE BENEFITS:")
            print(f"   ✓ Audio split into {self.num_splits} parts for better reliability")
            print(f"   ✓ Each part transcribed separately")
            print(f"   ✓ Timestamps automatically synchronized")
            print(f"   ✓ Better coverage of entire audio")
            
            # Handle audio file
            if keep_audio:
                final_audio_path = video_path_obj.with_suffix('.mp3')
                if temp_audio != final_audio_path:
                    os.rename(temp_audio, final_audio_path)
                    temp_audio = None
                print(f"\n   Audio saved: {final_audio_path}")
                return str(output_srt_path), str(final_audio_path)
            
            return str(output_srt_path), audio_path
            
        finally:
            if temp_audio and not keep_audio and os.path.exists(temp_audio):
                try:
                    os.remove(temp_audio)
                    print(f"\n   Cleaned up temporary audio file")
                except:
                    pass


def main():
    """Main entry point for command-line usage."""
    parser = argparse.ArgumentParser(
        description="Convert video to English SRT subtitles with smart audio splitting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Split audio into 3 parts (default)
  python video_to_english_srt_split.py input_video.mp4

  # Split into 5 parts for longer videos
  python video_to_english_srt_split.py input_video.mp4 --splits 5
  
  # Replace words in subtitles
  python video_to_english_srt_split.py input_video.mp4 --replace pooja:Rucha
  
  # Multiple word replacements
  python video_to_english_srt_split.py input_video.mp4 --replace pooja:Rucha --replace Rocha:Rucha

  # Local mode
  python video_to_english_srt_split.py input_video.mp4 --local

  # Specify output
  python video_to_english_srt_split.py input_video.mp4 -o output.srt

Benefits of Split Mode:
  - Better coverage of entire audio (no missing segments at end)
  - More reliable for longer videos
  - Splits at silent moments for natural boundaries
  - Automatic timestamp synchronization
        """
    )
    
    parser.add_argument(
        "video",
        help="Path to input video file"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Path to output SRT file (default: same as video with .srt extension)"
    )
    
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep extracted audio file"
    )
    
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (or set OPENAI_API_KEY environment variable)"
    )
    
    parser.add_argument(
        "--language",
        default="hi",
        help="Source language code (default: hi for Hindi)"
    )
    
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local Whisper instead of API"
    )
    
    parser.add_argument(
        "--model-size",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size for local mode (default: base)"
    )
    
    parser.add_argument(
        "--splits",
        type=int,
        default=3,
        help="Number of parts to split audio into (default: 3, recommended: 3-5, use 1 for no splitting)"
    )
    
    parser.add_argument(
        "--replace",
        action="append",
        metavar="OLD:NEW",
        help="Replace words in subtitles (format: old:new). Can be used multiple times. Example: --replace pooja:Rucha"
    )
    
    args = parser.parse_args()
    
    try:
        # Parse word replacements
        word_replacements = None
        if args.replace:
            word_replacements = {}
            for replacement in args.replace:
                if ':' not in replacement:
                    print(f"⚠️  Warning: Skipping invalid replacement format '{replacement}' (should be old:new)")
                    continue
                old, new = replacement.split(':', 1)
                word_replacements[old.strip()] = new.strip()
            
            if word_replacements:
                print(f"\n🔄 Word replacements configured:")
                for old, new in word_replacements.items():
                    print(f"   '{old}' → '{new}'")
        
        # Create converter
        converter = VideoToSRTConverter(
            api_key=args.api_key,
            use_local=args.local,
            model_size=args.model_size,
            num_splits=args.splits
        )
        
        # Convert video to SRT
        srt_path, audio_path = converter.convert_video_to_srt(
            video_path=args.video,
            output_srt_path=args.output,
            keep_audio=args.keep_audio,
            source_language=args.language,
            word_replacements=word_replacements
        )
        
        print("\n" + "="*60)
        print("CONVERSION COMPLETE!")
        print("="*60)
        print(f"Video:     {args.video}")
        print(f"Subtitles: {srt_path}")
        if args.keep_audio:
            print(f"Audio:     {audio_path}")
        print("\n✅ Split-mode ensures better coverage and reliability!")
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

