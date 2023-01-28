# flake8: noqa:E501

from cast.models import get_video_dimensions


class TestVideoDimensions:
    def test_video_from_ios_device_portrait(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
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

    def test_video_from_ios_device_landscape(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/jochen/projects/homepage/homepage/media/cast_videos/57305469432__3391A666-61B4-4EEA-9373-119115C8DF9F.MOV':
  Metadata:
    major_brand     : qt
    minor_version   : 0
    compatible_brands: qt
    creation_time   : 2019-02-28T13:51:35.000000Z
    com.apple.quicktime.make: Apple
    com.apple.quicktime.model: iPhone XS
    com.apple.quicktime.software: 12.1.4
    com.apple.quicktime.creationdate: 2019-02-28T14:51:34+0100
  Duration: 00:00:02.73, start: 0.000000, bitrate: 1087 kb/s
    Stream #0:0(und): Video: h264 (Baseline) (avc1 / 0x31637661), yuv420p(tv, smpte170m/bt709/bt709), 480x360, 977 kb/s, 30 fps, 30 tbr, 600 tbn, 1200 tbc (default)
    Metadata:
      creation_time   : 2019-02-28T13:51:35.000000Z
      handler_name    : Core Media Video
      encoder         : H.264
    Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 88 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T13:51:35.000000Z
      handler_name    : Core Media Audio
    Stream #0:2(und): Data: none (mebx / 0x7862656D), 0 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T13:51:35.000000Z
      handler_name    : Core Media Metadata
    Stream #0:3(und): Data: none (mebx / 0x7862656D), 0 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T13:51:35.000000Z
      handler_name    : Core Media Metadata
Stream mapping:
  Stream #0:0 -> #0:0 (h264 (native) -> mjpeg (native))
Press [q] to stop, [?] for help
[swscaler @ 0x7fe8dd0c7600] deprecated pixel format used, make sure you did set range correctly
Output #0, image2, to '/var/folders/yq/lq6vnk9s693bp4xr5wktm1vh0000gn/T/poster_p5k4i2f3.jpg':
  Metadata:
    major_brand     : qt
    minor_version   : 0
    compatible_brands: qt
    com.apple.quicktime.creationdate: 2019-02-28T14:51:34+0100
    com.apple.quicktime.make: Apple
    com.apple.quicktime.model: iPhone XS
    com.apple.quicktime.software: 12.1.4
    encoder         : Lavf58.20.100
    Stream #0:0(und): Video: mjpeg, yuvj420p(pc), 480x360, q=2-31, 200 kb/s, 30 fps, 30 tbn, 30 tbc (default)
    Metadata:
      creation_time   : 2019-02-28T13:51:35.000000Z
      handler_name    : Core Media Video
      encoder         : Lavc58.35.100 mjpeg
    Side data:
      cpb: bitrate max/min/avg: 0/0/200000 buffer size: 0 vbv_delay: -1
frame=    1 fps=0.0 q=6.2 Lsize=N/A time=00:00:00.03 bitrate=N/A speed=2.47x
video:22kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        print("width x height: ", width, height)
        assert width == 480
        assert height == 360

    def test_video_from_ios_portrait(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/jochen/projects/homepage/homepage/media/cast_videos/E6B2E327-98BB-4348-8606-1E531D121BB3.MOV':
  Metadata:
    major_brand     : qt
    minor_version   : 0
    compatible_brands: qt
    creation_time   : 2019-02-28T13:55:07.000000Z
    com.apple.quicktime.location.ISO6709: +51.2382+006.7899+036.689/
    com.apple.quicktime.make: Apple
    com.apple.quicktime.model: iPhone XS
    com.apple.quicktime.software: 12.1.4
    com.apple.quicktime.creationdate: 2019-02-28T14:55:06+0100
  Duration: 00:00:03.57, start: 0.000000, bitrate: 28918 kb/s
    Stream #0:0(und): Video: hevc (Main) (hvc1 / 0x31637668), yuv420p(tv, bt709), 3840x2160, 28726 kb/s, 29.97 fps, 29.97 tbr, 600 tbn, 600 tbc (default)
    Metadata:
      rotate          : 90
      creation_time   : 2019-02-28T13:55:07.000000Z
      handler_name    : Core Media Video
      encoder         : HEVC
    Side data:
      displaymatrix: rotation of -90.00 degrees
    Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 168 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T13:55:07.000000Z
      handler_name    : Core Media Audio
    Stream #0:2(und): Data: none (mebx / 0x7862656D), 0 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T13:55:07.000000Z
      handler_name    : Core Media Metadata
    Stream #0:3(und): Data: none (mebx / 0x7862656D), 0 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T13:55:07.000000Z
      handler_name    : Core Media Metadata
Stream mapping:
  Stream #0:0 -> #0:0 (hevc (native) -> mjpeg (native))
Press [q] to stop, [?] for help
[swscaler @ 0x7fdc29801000] deprecated pixel format used, make sure you did set range correctly
Output #0, image2, to '/var/folders/yq/lq6vnk9s693bp4xr5wktm1vh0000gn/T/poster_3w_mupml.jpg':
  Metadata:
    major_brand     : qt
    minor_version   : 0
    compatible_brands: qt
    com.apple.quicktime.creationdate: 2019-02-28T14:55:06+0100
    com.apple.quicktime.location.ISO6709: +51.2382+006.7899+036.689/
    com.apple.quicktime.make: Apple
    com.apple.quicktime.model: iPhone XS
    com.apple.quicktime.software: 12.1.4
    encoder         : Lavf58.20.100
    Stream #0:0(und): Video: mjpeg, yuvj420p(pc), 2160x3840, q=2-31, 200 kb/s, 29.97 fps, 29.97 tbn, 29.97 tbc (default)
    Metadata:
      encoder         : Lavc58.35.100 mjpeg
      creation_time   : 2019-02-28T13:55:07.000000Z
      handler_name    : Core Media Video
    Side data:
      cpb: bitrate max/min/avg: 0/0/200000 buffer size: 0 vbv_delay: -1
      displaymatrix: rotation of -0.00 degrees
frame=    1 fps=0.0 q=8.8 Lsize=N/A time=00:00:00.03 bitrate=N/A speed=0.0517x
video:211kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        print("width x height: ", width, height)
        assert width == 2160
        assert height == 3840

    def test_video_from_android_portrait(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/jochen/projects/homepage/homepage/media/cast_videos/VID_20190228_144156.mp4':
  Metadata:
    major_brand     : mp42
    minor_version   : 0
    compatible_brands: isommp42
    creation_time   : 2019-02-28T13:41:56.000000Z
    location        : +51.2380+006.7902/
    location-eng    : +51.2380+006.7902/
    com.android.version: 9
  Duration: 00:00:04.06, start: 0.000000, bitrate: 21343 kb/s
    Stream #0:0(eng): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 190 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T13:41:56.000000Z
      handler_name    : SoundHandle
    Stream #0:1(eng): Video: h264 (High) (avc1 / 0x31637661), yuvj420p(pc, bt470bg/bt470bg/smpte170m), 1920x1080, 21917 kb/s, SAR 1:1 DAR 16:9, 29.88 fps, 30.13 tbr, 90k tbn, 180k tbc (default)
    Metadata:
      rotate          : 270
      creation_time   : 2019-02-28T13:41:56.000000Z
      handler_name    : VideoHandle
    Side data:
      displaymatrix: rotation of 90.00 degrees
Stream mapping:
  Stream #0:1 -> #0:0 (h264 (native) -> mjpeg (native))
Press [q] to stop, [?] for help
Output #0, image2, to '/var/folders/yq/lq6vnk9s693bp4xr5wktm1vh0000gn/T/poster_22_kvc0v.jpg':
  Metadata:
    major_brand     : mp42
    minor_version   : 0
    compatible_brands: isommp42
    com.android.version: 9
    location        : +51.2380+006.7902/
    location-eng    : +51.2380+006.7902/
    encoder         : Lavf58.20.100
    Stream #0:0(eng): Video: mjpeg, yuvj420p(pc), 1080x1920 [SAR 1:1 DAR 9:16], q=2-31, 200 kb/s, 30.13 fps, 30.13 tbn, 30.13 tbc (default)
    Metadata:
      encoder         : Lavc58.35.100 mjpeg
      creation_time   : 2019-02-28T13:41:56.000000Z
      handler_name    : VideoHandle
    Side data:
      cpb: bitrate max/min/avg: 0/0/200000 buffer size: 0 vbv_delay: -1
      displaymatrix: rotation of -0.00 degrees
frame=    1 fps=0.0 q=6.4 Lsize=N/A time=00:00:00.03 bitrate=N/A speed=0.263x
video:97kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        assert width == 1080
        assert height == 1920

    def test_video_from_android_landscape(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/jochen/projects/homepage/homepage/media/cast_videos/VID_20190228_150527.mp4':
  Metadata:
    major_brand     : mp42
    minor_version   : 0
    compatible_brands: isommp42
    creation_time   : 2019-02-28T14:05:27.000000Z
    location        : +51.2380+006.7902/
    location-eng    : +51.2380+006.7902/
    com.android.version: 9
  Duration: 00:00:02.23, start: 0.000000, bitrate: 22175 kb/s
    Stream #0:0(eng): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 193 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T14:05:27.000000Z
      handler_name    : SoundHandle
    Stream #0:1(eng): Video: h264 (High) (avc1 / 0x31637661), yuvj420p(pc, bt470bg/bt470bg/smpte170m), 1920x1080, 21968 kb/s, SAR 1:1 DAR 16:9, 30.01 fps, 30 tbr, 90k tbn, 180k tbc (default)
    Metadata:
      creation_time   : 2019-02-28T14:05:27.000000Z
      handler_name    : VideoHandle
Stream mapping:
  Stream #0:1 -> #0:0 (h264 (native) -> mjpeg (native))
Press [q] to stop, [?] for help
Output #0, image2, to '/var/folders/yq/lq6vnk9s693bp4xr5wktm1vh0000gn/T/poster_qcptirnt.jpg':
  Metadata:
    major_brand     : mp42
    minor_version   : 0
    compatible_brands: isommp42
    com.android.version: 9
    location        : +51.2380+006.7902/
    location-eng    : +51.2380+006.7902/
    encoder         : Lavf58.20.100
    Stream #0:0(eng): Video: mjpeg, yuvj420p(pc), 1920x1080 [SAR 1:1 DAR 16:9], q=2-31, 200 kb/s, 30 fps, 30 tbn, 30 tbc (default)
    Metadata:
      creation_time   : 2019-02-28T14:05:27.000000Z
      handler_name    : VideoHandle
      encoder         : Lavc58.35.100 mjpeg
    Side data:
      cpb: bitrate max/min/avg: 0/0/200000 buffer size: 0 vbv_delay: -1
frame=    1 fps=0.0 q=6.4 Lsize=N/A time=00:00:00.03 bitrate=N/A speed=0.332x
video:75kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        assert width == 1920
        assert height == 1080

    def test_video_from_handbrake_landscape(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/jochen/projects/homepage/homepage/media/cast_videos/IMG_0563_kqTcRSQ.mp4':
  Metadata:
    major_brand     : mp42
    minor_version   : 512
    compatible_brands: isomiso2avc1mp41
    creation_time   : 2019-02-28T11:33:03.000000Z
    title           : Ein langes Brillenvideo
    date            : 2018-08-21T12:28:17+0200
    encoder         : HandBrake 1.2.1 2019021700
  Duration: 00:04:32.19, start: 0.000000, bitrate: 3104 kb/s
    Stream #0:0(und): Video: h264 (Main) (avc1 / 0x31637661), yuv420p(tv, bt709), 1920x1080 [SAR 1:1 DAR 16:9], 2931 kb/s, 30 fps, 30 tbr, 90k tbn, 180k tbc (default)
    Metadata:
      creation_time   : 2019-02-28T11:33:03.000000Z
      handler_name    : VideoHandler
    Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 164 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T11:33:03.000000Z
      handler_name    : SoundHandler
Stream mapping:
  Stream #0:0 -> #0:0 (h264 (native) -> mjpeg (native))
Press [q] to stop, [?] for help
[swscaler @ 0x7f8a4513ac00] deprecated pixel format used, make sure you did set range correctly
Output #0, image2, to '/var/folders/yq/lq6vnk9s693bp4xr5wktm1vh0000gn/T/poster_abfyafdr.jpg':
  Metadata:
    major_brand     : mp42
    minor_version   : 512
    compatible_brands: isomiso2avc1mp41
    date            : 2018-08-21T12:28:17+0200
    title           : Ein langes Brillenvideo
    encoder         : Lavf58.20.100
    Stream #0:0(und): Video: mjpeg, yuvj420p(pc), 1920x1080 [SAR 1:1 DAR 16:9], q=2-31, 200 kb/s, 30 fps, 30 tbn, 30 tbc (default)
    Metadata:
      creation_time   : 2019-02-28T11:33:03.000000Z
      handler_name    : VideoHandler
      encoder         : Lavc58.35.100 mjpeg
    Side data:
      cpb: bitrate max/min/avg: 0/0/200000 buffer size: 0 vbv_delay: -1
frame=    1 fps=0.0 q=8.6 Lsize=N/A time=00:00:00.03 bitrate=N/A speed=0.194x
video:84kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        assert width == 1920
        assert height == 1080

    def test_video_from_ios_fotos_landscape(self):
        ffmpeg_output = """
ffmpeg version 4.1.1 Copyright (c) 2000-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.0 (clang-1000.11.45.5)
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/jochen/projects/homepage/homepage/media/cast_videos/IMG_0563.m4v':
  Metadata:
    major_brand     : M4V
    minor_version   : 1
    compatible_brands: M4V M4A mp42isom
    creation_time   : 2019-02-28T11:29:47.000000Z
    date            : 2018-08-21T12:28:17+0200
    title           : Ein langes Brillenvideo
    make            : Apple
  Duration: 00:04:32.11, start: 0.000000, bitrate: 10591 kb/s
    Stream #0:0(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 88 kb/s (default)
    Metadata:
      creation_time   : 2019-02-28T11:29:47.000000Z
      handler_name    : Core Media Audio
    Stream #0:1(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709), 1920x1080 [SAR 1:1 DAR 16:9], 10497 kb/s, 30.01 fps, 30 tbr, 600 tbn, 1200 tbc (default)
    Metadata:
      creation_time   : 2019-02-28T11:29:47.000000Z
      handler_name    : Core Media Video
Stream mapping:
  Stream #0:1 -> #0:0 (h264 (native) -> mjpeg (native))
Press [q] to stop, [?] for help
[swscaler @ 0x7f8115882e00] deprecated pixel format used, make sure you did set range correctly
Output #0, image2, to '/var/folders/yq/lq6vnk9s693bp4xr5wktm1vh0000gn/T/poster_5rsf6f9y.jpg':
  Metadata:
    major_brand     : M4V
    minor_version   : 1
    compatible_brands: M4V M4A mp42isom
    make            : Apple
    date            : 2018-08-21T12:28:17+0200
    title           : Ein langes Brillenvideo
    encoder         : Lavf58.20.100
    Stream #0:0(und): Video: mjpeg, yuvj420p(pc), 1920x1080 [SAR 1:1 DAR 16:9], q=2-31, 200 kb/s, 30 fps, 30 tbn, 30 tbc (default)
    Metadata:
      creation_time   : 2019-02-28T11:29:47.000000Z
      handler_name    : Core Media Video
      encoder         : Lavc58.35.100 mjpeg
    Side data:
      cpb: bitrate max/min/avg: 0/0/200000 buffer size: 0 vbv_delay: -1
frame=    1 fps=0.0 q=8.6 Lsize=N/A time=00:00:00.03 bitrate=N/A speed=0.269x
video:91kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        assert width == 1920
        assert height == 1080

    def test_video_from_handbrake_portrait(self):
        ffmpeg_output = """
ffprobe version 4.1.3 Copyright (c) 2007-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.1 (clang-1001.0.46.4)
  configuration: --prefix=/usr/local/Cellar/ffmpeg/4.1.3_1 --enable-shared --enable-pthreads --enable-version3 --enable-hardcoded-tables --enable-avresample --cc=clang --host-cflags='-I/Library/Java/JavaVirtualMachines/adoptopenjdk-11.0.2.jdk/Contents/Home/include -I/Library/Java/JavaVirtualMachines/adoptopenjdk-11.0.2.jdk/Contents/Home/include/darwin' --host-ldflags= --enable-ffplay --enable-gnutls --enable-gpl --enable-libaom --enable-libbluray --enable-libmp3lame --enable-libopus --enable-librubberband --enable-libsnappy --enable-libtesseract --enable-libtheora --enable-libvorbis --enable-libvpx --enable-libx264 --enable-libx265 --enable-libxvid --enable-lzma --enable-libfontconfig --enable-libfreetype --enable-frei0r --enable-libass --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenjpeg --enable-librtmp --enable-libspeex --enable-videotoolbox --disable-libjack --disable-indev=jack --enable-libaom --enable-libsoxr
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'Michaelsbergschaukel.mp4':
  Metadata:
    major_brand     : mp42
    minor_version   : 512
    compatible_brands: isomiso2avc1mp41
    creation_time   : 2019-04-27T00:04:26.000000Z
    title           : Michaelsbergschaukel
    date            : 2018-09-22T14:58:10+0200
    encoder         : HandBrake 1.2.1 2019021700
  Duration: 00:00:13.79, start: 0.000000, bitrate: 10086 kb/s
    Stream #0:0(und): Video: h264 (Main) (avc1 / 0x31637661), yuv420p(tv, bt709), 1920x1080 [SAR 81:256 DAR 9:16], 9970 kb/s, 29.97 fps, 29.97 tbr, 90k tbn, 180k tbc (default)
    Metadata:
      creation_time   : 2019-04-27T00:04:26.000000Z
      handler_name    : VideoHandler
    Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 162 kb/s (default)
    Metadata:
      creation_time   : 2019-04-27T00:04:26.000000Z
      handler_name    : SoundHandler
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        print("width x height: ", width, height)
        assert width == 1080
        assert height == 1920

    def test_video_from_handbrake_landscape_2(self):
        ffmpeg_output = """
ffprobe version 4.1.3 Copyright (c) 2007-2019 the FFmpeg developers
  built with Apple LLVM version 10.0.1 (clang-1001.0.46.4)
  configuration: --prefix=/usr/local/Cellar/ffmpeg/4.1.3_1 --enable-shared --enable-pthreads --enable-version3 --enable-hardcoded-tables --enable-avresample --cc=clang --host-cflags='-I/Library/Java/JavaVirtualMachines/adoptopenjdk-11.0.2.jdk/Contents/Home/include -I/Library/Java/JavaVirtualMachines/adoptopenjdk-11.0.2.jdk/Contents/Home/include/darwin' --host-ldflags= --enable-ffplay --enable-gnutls --enable-gpl --enable-libaom --enable-libbluray --enable-libmp3lame --enable-libopus --enable-librubberband --enable-libsnappy --enable-libtesseract --enable-libtheora --enable-libvorbis --enable-libvpx --enable-libx264 --enable-libx265 --enable-libxvid --enable-lzma --enable-libfontconfig --enable-libfreetype --enable-frei0r --enable-libass --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenjpeg --enable-librtmp --enable-libspeex --enable-videotoolbox --disable-libjack --disable-indev=jack --enable-libaom --enable-libsoxr
  libavutil      56. 22.100 / 56. 22.100
  libavcodec     58. 35.100 / 58. 35.100
  libavformat    58. 20.100 / 58. 20.100
  libavdevice    58.  5.100 / 58.  5.100
  libavfilter     7. 40.101 /  7. 40.101
  libavresample   4.  0.  0 /  4.  0.  0
  libswscale      5.  3.100 /  5.  3.100
  libswresample   3.  3.100 /  3.  3.100
  libpostproc    55.  3.100 / 55.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'Tripptrappkuckuck.mp4':
  Metadata:
    major_brand     : mp42
    minor_version   : 512
    compatible_brands: isomiso2avc1mp41
    creation_time   : 2019-04-27T00:12:09.000000Z
    title           : Tripptrappkuckuck
    date            : 2018-09-25T21:25:49+0200
    encoder         : HandBrake 1.2.1 2019021700
  Duration: 00:00:41.82, start: 0.000000, bitrate: 2030 kb/s
    Stream #0:0(und): Video: h264 (Main) (avc1 / 0x31637661), yuv420p(tv, bt709), 1920x1080 [SAR 1:1 DAR 16:9], 1860 kb/s, 29.97 fps, 29.97 tbr, 90k tbn, 180k tbc (default)
    Metadata:
      creation_time   : 2019-04-27T00:12:09.000000Z
      handler_name    : VideoHandler
    Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 162 kb/s (default)
    Metadata:
      creation_time   : 2019-04-27T00:12:09.000000Z
      handler_name    : SoundHandler
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        assert width == 1920
        assert height == 1080

    def test_video_from_empty(self):
        ffmpeg_output = """
           foo bar baz
        """
        width, height = get_video_dimensions(ffmpeg_output.split("\n"))
        assert width is None
        assert height is None
