import pytest

from cast.models import get_video_dimensions


class TestVideoDimensions:
    def test_video_from_ios(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
  configuration: --prefix=/usr/local/Cellar/ffmpeg/4.1.1 --enable-shared --enable-pthreads --enable-version3 --enable-hardcoded-tables --enable-avresample --cc=clang --host-cflags='-I/Library/Java/JavaVirtualMachines/openjdk-11.0.2.jdk/Contents/Home/include -I/Library/Java/JavaVirtualMachines/openjdk-11.0.2.jdk/Contents/Home/include/darwin' --host-ldflags= --enable-ffplay --enable-gnutls --enable-gpl --enable-libaom --enable-libbluray --enable-libmp3lame --enable-libopus --enable-librubberband --enable-libsnappy --enable-libtesseract --enable-libtheora --enable-libvorbis --enable-libvpx --enable-libx264 --enable-libx265 --enable-libxvid --enable-lzma --enable-libfontconfig --enable-libfreetype --enable-frei0r --enable-libass --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenjpeg --enable-librtmp --enable-libspeex --enable-videotoolbox --disable-libjack --disable-indev=jack --enable-libaom --enable-libsoxr
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/jochen/projects/homepage/homepage/media/cast_videos/57304811027__F8E67B21-7B33-4C70-842D-D7E708DCA683.MOV':
  Metadata:
    major_brand     : qt
    minor_version   : 0
    compatible_brands: qt
    creation_time   : 2019-02-28T12:01:50.000000Z
    com.apple.quicktime.make: Apple
    com.apple.quicktime.model: iPhone XS
    com.apple.quicktime.software: 12.1.4
    com.apple.quicktime.creationdate: 2019-02-28T13:01:50+0100
  Duration: 00:00:04.90, start: 0.000000, bitrate: 908 kb/s
    Stream #0:0(und): Video: h264 (Baseline) (avc1 / 0x31637661), yuv420p(tv, smpte170m/bt709/bt709), 480x360, 778 kb/s, 30.01 fps, 30 tbr, 600 tbn, 1200 tbc (default)
    Metadata:
      rotate          : 90
      creation_time   : 2019-02-28T12:01:50.000000Z
      handler_name    : Core Media Video
      encoder         : H.264
    Side data:
      displaymatrix: rotation of -90.00 degrees
    Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 91 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T12:01:50.000000Z
      handler_name    : Core Media Audio
    Stream #0:2(und): Data: none (mebx / 0x7862656D), 23 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T12:01:50.000000Z
      handler_name    : Core Media Metadata
    Stream #0:3(und): Data: none (mebx / 0x7862656D), 0 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T12:01:50.000000Z
      handler_name    : Core Media Metadata
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        print("width x height: ", width, height)
        assert width == 360
        assert height == 480
