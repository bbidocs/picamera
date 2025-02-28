# vim: set et sw=4 sts=4 fileencoding=utf-8:
#
# Python header conversion
# Copyright (c) 2013-2015 Dave Jones <dave@waveform.org.uk>
#
# Original headers
# Copyright (c) 2012, Broadcom Europe Ltd
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from __future__ import (
    unicode_literals,
    print_function,
    division,
    absolute_import,
    )

# Make Py2's str equivalent to Py3's
str = type('')

import io
import ctypes as ct
import warnings
import weakref
from threading import Thread, Event
try:
    from queue import Queue, Empty
except ImportError:
    from Queue import Queue, Empty
from collections import namedtuple
from fractions import Fraction
from itertools import cycle

from . import bcm_host, mmal
from .streams import BufferIO
from .exc import (
    mmal_check,
    PiCameraValueError,
    PiCameraRuntimeError,
    PiCameraMMALError,
    PiCameraDeprecated,
    )


# Old firmwares confuse the RGB24 and BGR24 encodings. This flag tracks whether
# the order needs fixing (it is set during MMALCamera.__init__).
FIX_RGB_BGR_ORDER = None

# Mapping of parameters to the C-structure they expect / return. If a parameter
# does not appear in this mapping, it cannot be queried / set with the
# MMALControlPort.params attribute.
PARAM_TYPES = {
    mmal.MMAL_PARAMETER_ALGORITHM_CONTROL:              mmal.MMAL_PARAMETER_ALGORITHM_CONTROL_T,
    mmal.MMAL_PARAMETER_ANNOTATE:                       None, # adjusted by MMALCamera.annotate_rev
    mmal.MMAL_PARAMETER_ANTISHAKE:                      mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_AUDIO_LATENCY_TARGET:           mmal.MMAL_PARAMETER_AUDIO_LATENCY_TARGET_T,
    mmal.MMAL_PARAMETER_AWB_MODE:                       mmal.MMAL_PARAMETER_AWBMODE_T,
    mmal.MMAL_PARAMETER_BRIGHTNESS:                     mmal.MMAL_PARAMETER_RATIONAL_T,
    mmal.MMAL_PARAMETER_BUFFER_FLAG_FILTER:             mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_BUFFER_REQUIREMENTS:            mmal.MMAL_PARAMETER_BUFFER_REQUIREMENTS_T,
    mmal.MMAL_PARAMETER_CAMERA_BURST_CAPTURE:           mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_CAMERA_CLOCKING_MODE:           mmal.MMAL_PARAMETER_CAMERA_CLOCKING_MODE_T,
    mmal.MMAL_PARAMETER_CAMERA_CONFIG:                  mmal.MMAL_PARAMETER_CAMERA_CONFIG_T,
    mmal.MMAL_PARAMETER_CAMERA_CUSTOM_SENSOR_CONFIG:    mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_CAMERA_INFO:                    None, # adjusted by MMALCameraInfo.info_rev
    mmal.MMAL_PARAMETER_CAMERA_INTERFACE:               mmal.MMAL_PARAMETER_CAMERA_INTERFACE_T,
    mmal.MMAL_PARAMETER_CAMERA_MIN_ISO:                 mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_CAMERA_NUM:                     mmal.MMAL_PARAMETER_INT32_T,
    mmal.MMAL_PARAMETER_CAMERA_RX_CONFIG:               mmal.MMAL_PARAMETER_CAMERA_RX_CONFIG_T,
    mmal.MMAL_PARAMETER_CAMERA_RX_TIMING:               mmal.MMAL_PARAMETER_CAMERA_RX_TIMING_T,
    mmal.MMAL_PARAMETER_CAMERA_SETTINGS:                mmal.MMAL_PARAMETER_CAMERA_SETTINGS_T,
    mmal.MMAL_PARAMETER_CAMERA_USE_CASE:                mmal.MMAL_PARAMETER_CAMERA_USE_CASE_T,
    mmal.MMAL_PARAMETER_CAPTURE_EXPOSURE_COMP:          mmal.MMAL_PARAMETER_INT32_T,
    mmal.MMAL_PARAMETER_CAPTURE:                        mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_CAPTURE_MODE:                   mmal.MMAL_PARAMETER_CAPTUREMODE_T,
    mmal.MMAL_PARAMETER_CAPTURE_STATS_PASS:             mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_CAPTURE_STATUS:                 mmal.MMAL_PARAMETER_CAPTURE_STATUS_T,
    mmal.MMAL_PARAMETER_CHANGE_EVENT_REQUEST:           mmal.MMAL_PARAMETER_CHANGE_EVENT_REQUEST_T,
    mmal.MMAL_PARAMETER_CLOCK_ACTIVE:                   mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_CLOCK_DISCONT_THRESHOLD:        mmal.MMAL_PARAMETER_CLOCK_DISCONT_THRESHOLD_T,
    mmal.MMAL_PARAMETER_CLOCK_ENABLE_BUFFER_INFO:       mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_CLOCK_FRAME_RATE:               mmal.MMAL_PARAMETER_RATIONAL_T,
    mmal.MMAL_PARAMETER_CLOCK_LATENCY:                  mmal.MMAL_PARAMETER_CLOCK_LATENCY_T,
    mmal.MMAL_PARAMETER_CLOCK_REQUEST_THRESHOLD:        mmal.MMAL_PARAMETER_CLOCK_REQUEST_THRESHOLD_T,
    mmal.MMAL_PARAMETER_CLOCK_SCALE:                    mmal.MMAL_PARAMETER_RATIONAL_T,
    mmal.MMAL_PARAMETER_CLOCK_TIME:                     mmal.MMAL_PARAMETER_INT64_T,
    mmal.MMAL_PARAMETER_CLOCK_UPDATE_THRESHOLD:         mmal.MMAL_PARAMETER_CLOCK_UPDATE_THRESHOLD_T,
    mmal.MMAL_PARAMETER_COLOUR_EFFECT:                  mmal.MMAL_PARAMETER_COLOURFX_T,
    mmal.MMAL_PARAMETER_CONTRAST:                       mmal.MMAL_PARAMETER_RATIONAL_T,
    mmal.MMAL_PARAMETER_CORE_STATISTICS:                mmal.MMAL_PARAMETER_CORE_STATISTICS_T,
    mmal.MMAL_PARAMETER_CUSTOM_AWB_GAINS:               mmal.MMAL_PARAMETER_AWB_GAINS_T,
    mmal.MMAL_PARAMETER_DISPLAYREGION:                  mmal.MMAL_DISPLAYREGION_T,
    mmal.MMAL_PARAMETER_DPF_CONFIG:                     mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_DYNAMIC_RANGE_COMPRESSION:      mmal.MMAL_PARAMETER_DRC_T,
    mmal.MMAL_PARAMETER_ENABLE_RAW_CAPTURE:             mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_EXIF_DISABLE:                   mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_EXIF:                           mmal.MMAL_PARAMETER_EXIF_T,
    mmal.MMAL_PARAMETER_EXP_METERING_MODE:              mmal.MMAL_PARAMETER_EXPOSUREMETERINGMODE_T,
    mmal.MMAL_PARAMETER_EXPOSURE_COMP:                  mmal.MMAL_PARAMETER_INT32_T,
    mmal.MMAL_PARAMETER_EXPOSURE_MODE:                  mmal.MMAL_PARAMETER_EXPOSUREMODE_T,
    mmal.MMAL_PARAMETER_EXTRA_BUFFERS:                  mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_FIELD_OF_VIEW:                  mmal.MMAL_PARAMETER_FIELD_OF_VIEW_T,
    mmal.MMAL_PARAMETER_FLASH:                          mmal.MMAL_PARAMETER_FLASH_T,
    mmal.MMAL_PARAMETER_FLASH_REQUIRED:                 mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_FLASH_SELECT:                   mmal.MMAL_PARAMETER_FLASH_SELECT_T,
    mmal.MMAL_PARAMETER_FLICKER_AVOID:                  mmal.MMAL_PARAMETER_FLICKERAVOID_T,
    mmal.MMAL_PARAMETER_FOCUS:                          mmal.MMAL_PARAMETER_FOCUS_T,
    mmal.MMAL_PARAMETER_FOCUS_REGIONS:                  mmal.MMAL_PARAMETER_FOCUS_REGIONS_T,
    mmal.MMAL_PARAMETER_FOCUS_STATUS:                   mmal.MMAL_PARAMETER_FOCUS_STATUS_T,
    mmal.MMAL_PARAMETER_FPS_RANGE:                      mmal.MMAL_PARAMETER_FPS_RANGE_T,
    mmal.MMAL_PARAMETER_FRAME_RATE:                     mmal.MMAL_PARAMETER_RATIONAL_T, # actually mmal.MMAL_PARAMETER_FRAME_RATE_T but this only contains a rational anyway...
    mmal.MMAL_PARAMETER_IMAGE_EFFECT:                   mmal.MMAL_PARAMETER_IMAGEFX_T,
    mmal.MMAL_PARAMETER_IMAGE_EFFECT_PARAMETERS:        mmal.MMAL_PARAMETER_IMAGEFX_PARAMETERS_T,
    mmal.MMAL_PARAMETER_INPUT_CROP:                     mmal.MMAL_PARAMETER_INPUT_CROP_T,
    mmal.MMAL_PARAMETER_INTRAPERIOD:                    mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_ISO:                            mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_JPEG_ATTACH_LOG:                mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_JPEG_Q_FACTOR:                  mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_LOCKSTEP_ENABLE:                mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_LOGGING:                        mmal.MMAL_PARAMETER_LOGGING_T,
    mmal.MMAL_PARAMETER_MB_ROWS_PER_SLICE:              mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_MEM_USAGE:                      mmal.MMAL_PARAMETER_MEM_USAGE_T,
    mmal.MMAL_PARAMETER_MINIMISE_FRAGMENTATION:         mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_MIRROR:                         mmal.MMAL_PARAMETER_MIRROR_T,
    mmal.MMAL_PARAMETER_NALUNITFORMAT:                  mmal.MMAL_PARAMETER_VIDEO_NALUNITFORMAT_T,
    mmal.MMAL_PARAMETER_NO_IMAGE_PADDING:               mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_POWERMON_ENABLE:                mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_PRIVACY_INDICATOR:              mmal.MMAL_PARAMETER_PRIVACY_INDICATOR_T,
    mmal.MMAL_PARAMETER_PROFILE:                        mmal.MMAL_PARAMETER_VIDEO_PROFILE_T,
    mmal.MMAL_PARAMETER_RATECONTROL:                    mmal.MMAL_PARAMETER_VIDEO_RATECONTROL_T,
    mmal.MMAL_PARAMETER_REDEYE:                         mmal.MMAL_PARAMETER_REDEYE_T,
    mmal.MMAL_PARAMETER_ROTATION:                       mmal.MMAL_PARAMETER_INT32_T,
    mmal.MMAL_PARAMETER_SATURATION:                     mmal.MMAL_PARAMETER_RATIONAL_T,
    mmal.MMAL_PARAMETER_SEEK:                           mmal.MMAL_PARAMETER_SEEK_T,
    mmal.MMAL_PARAMETER_SENSOR_INFORMATION:             mmal.MMAL_PARAMETER_SENSOR_INFORMATION_T,
    mmal.MMAL_PARAMETER_SHARPNESS:                      mmal.MMAL_PARAMETER_RATIONAL_T,
    mmal.MMAL_PARAMETER_SHUTTER_SPEED:                  mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_STATISTICS:                     mmal.MMAL_PARAMETER_STATISTICS_T,
    mmal.MMAL_PARAMETER_STEREOSCOPIC_MODE:              mmal.MMAL_PARAMETER_STEREOSCOPIC_MODE_T,
    mmal.MMAL_PARAMETER_STILLS_DENOISE:                 mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_SUPPORTED_ENCODINGS:            mmal.MMAL_PARAMETER_ENCODING_T,
    mmal.MMAL_PARAMETER_SUPPORTED_PROFILES:             mmal.MMAL_PARAMETER_VIDEO_PROFILE_T,
    mmal.MMAL_PARAMETER_SW_SATURATION_DISABLE:          mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_SW_SHARPEN_DISABLE:             mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_SYSTEM_TIME:                    mmal.MMAL_PARAMETER_UINT64_T,
    mmal.MMAL_PARAMETER_THUMBNAIL_CONFIGURATION:        mmal.MMAL_PARAMETER_THUMBNAIL_CONFIG_T,
    mmal.MMAL_PARAMETER_URI:                            mmal.MMAL_PARAMETER_URI_T,
    mmal.MMAL_PARAMETER_USE_STC:                        mmal.MMAL_PARAMETER_CAMERA_STC_MODE_T,
    mmal.MMAL_PARAMETER_VIDEO_ALIGN_HORIZ:              mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ALIGN_VERT:               mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_BIT_RATE:                 mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_DENOISE:                  mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_DROPPABLE_PFRAMES:        mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_EEDE_ENABLE:              mmal.MMAL_PARAMETER_VIDEO_EEDE_ENABLE_T,
    mmal.MMAL_PARAMETER_VIDEO_EEDE_LOSSRATE:            mmal.MMAL_PARAMETER_VIDEO_EEDE_LOSSRATE_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_FRAME_LIMIT_BITS:  mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_INITIAL_QUANT:     mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_INLINE_HEADER:     mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_INLINE_VECTORS:    mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_MAX_QUANT:         mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_MIN_QUANT:         mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_PEAK_RATE:         mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_QP_P:              mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_RC_MODEL:          mmal.MMAL_PARAMETER_VIDEO_ENCODE_RC_MODEL_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_RC_SLICE_DQUANT:   mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_SEI_ENABLE:        mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_ENCODE_SPS_TIMINGS:       mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_FRAME_RATE:               mmal.MMAL_PARAMETER_RATIONAL_T, # actually mmal.MMAL_PARAMETER_FRAME_RATE_T but this only contains a rational anyway...
    mmal.MMAL_PARAMETER_VIDEO_IMMUTABLE_INPUT:          mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_INTERLACE_TYPE:           mmal.MMAL_PARAMETER_VIDEO_INTERLACE_TYPE_T,
    mmal.MMAL_PARAMETER_VIDEO_INTERPOLATE_TIMESTAMPS:   mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_INTRA_REFRESH:            mmal.MMAL_PARAMETER_VIDEO_INTRA_REFRESH_T,
    mmal.MMAL_PARAMETER_VIDEO_LEVEL_EXTENSION:          mmal.MMAL_PARAMETER_VIDEO_LEVEL_EXTENSION_T,
    mmal.MMAL_PARAMETER_VIDEO_MAX_NUM_CALLBACKS:        mmal.MMAL_PARAMETER_UINT32_T,
    mmal.MMAL_PARAMETER_VIDEO_RENDER_STATS:             mmal.MMAL_PARAMETER_VIDEO_RENDER_STATS_T,
    mmal.MMAL_PARAMETER_VIDEO_REQUEST_I_FRAME:          mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_VIDEO_STABILISATION:            mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_ZERO_COPY:                      mmal.MMAL_PARAMETER_BOOLEAN_T,
    mmal.MMAL_PARAMETER_ZERO_SHUTTER_LAG:               mmal.MMAL_PARAMETER_ZEROSHUTTERLAG_T,
    mmal.MMAL_PARAMETER_ZOOM:                           mmal.MMAL_PARAMETER_SCALEFACTOR_T,
    }


class PiCameraFraction(Fraction):
    """
    Extends :class:`~fractions.Fraction` to act as a (numerator, denominator)
    tuple when required.
    """
    def __len__(self):
        warnings.warn(
            PiCameraDeprecated(
                'Accessing framerate as a tuple is deprecated; this value is '
                'now a Fraction, so you can query the numerator and '
                'denominator properties directly, convert to an int or float, '
                'or perform arithmetic operations and comparisons directly'))
        return 2

    def __getitem__(self, index):
        warnings.warn(
            PiCameraDeprecated(
                'Accessing framerate as a tuple is deprecated; this value is '
                'now a Fraction, so you can query the numerator and '
                'denominator properties directly, convert to an int or float, '
                'or perform arithmetic operations and comparisons directly'))
        if index == 0:
            return self.numerator
        elif index == 1:
            return self.denominator
        else:
            raise IndexError('invalid index %d' % index)

    def __contains__(self, value):
        return value in (self.numerator, self.denominator)


class PiResolution(namedtuple('PiResolution', ('width', 'height'))):
    """
    A :func:`~collections.namedtuple` derivative which represents a resolution
    with a :attr:`width` and :attr:`height`.

    .. attribute:: width

        The width of the resolution in pixels

    .. attribute:: height

        The height of the resolution in pixels

    .. versionadded:: 1.11
    """

    __slots__ = () # workaround python issue #24931

    def pad(self, width=32, height=16):
        """
        Returns the resolution padded up to the nearest multiple of *width*
        and *height* which default to 32 and 16 respectively (the camera's
        native block size for most operations). For example:

        .. code-block:: pycon

            >>> PiResolution(1920, 1080).pad()
            PiResolution(width=1920, height=1088)
            >>> PiResolution(100, 100).pad(16, 16)
            PiResolution(width=128, height=112)
            >>> PiResolution(100, 100).pad(16, 16)
            PiResolution(width=112, height=112)
        """
        return PiResolution(
            width=((self.width + (width - 1)) // width) * width,
            height=((self.height + (height - 1)) // height) * height,
            )

    def transpose(self):
        """
        Returns the resolution with the width and height transposed. For
        example:

        .. code-block:: pycon

            >>> PiResolution(1920, 1080).transpose()
            PiResolution(width=1080, height=1920)
        """
        return PiResolution(self.height, self.width)

    def __str__(self):
        return '%dx%d' % (self.width, self.height)


def open_stream(stream, output=True, buffering=65536):
    """
    This is the core of picamera's IO-semantics. It returns a tuple of a
    file-like object and a bool indicating whether the stream requires closing
    once the caller is finished with it.

    * If *stream* is a string, it is opened as a file object (with mode 'wb' if
      *output* is ``True``, and the specified amount of *bufffering*). In this
      case the function returns ``(stream, True)``.

    * If *stream* is a stream with a ``write`` method, it is returned as
      ``(stream, False)``.

    * Otherwise *stream* is assumed to be a writeable buffer and is wrapped
      with :class:`BufferIO`. The function returns ``(stream, True)``.
    """
    if isinstance(stream, bytes):
        stream = stream.decode('ascii')
    opened = isinstance(stream, str)
    if opened:
        stream = io.open(stream, 'wb' if output else 'rb', buffering)
    else:
        try:
            if output:
                stream.write
            else:
                stream.read
        except AttributeError:
            # Assume the stream is actually a buffer
            opened = True
            stream = BufferIO(stream)
            if output and not stream.writable:
                raise IOError('writeable buffer required for output')
    return (stream, opened)


def close_stream(stream, opened):
    """
    If *opened* is ``True``, then the ``close`` method of *stream* will be
    called. Otherwise, the function will attempt to call the ``flush`` method
    on *stream* (if one exists). This function essentially takes the output
    of :func:`open_stream` and finalizes the result.
    """
    if opened:
        stream.close()
    else:
        try:
            stream.flush()
        except AttributeError:
            pass


def to_resolution(value):
    """
    Converts *value* which may be a (width, height) tuple or a string
    containing a representation of a resolution (e.g. "1024x768" or "1080p") to
    a (width, height) tuple.
    """
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    if isinstance(value, str):
        try:
            # A selection from https://en.wikipedia.org/wiki/Graphics_display_resolution
            # Feel free to suggest additions
            w, h = {
                'VGA':   (640, 480),
                'SVGA':  (800, 600),
                'XGA':   (1024, 768),
                'SXGA':  (1280, 1024),
                'UXGA':  (1600, 1200),
                'HD':    (1280, 720),
                'FHD':   (1920, 1080),
                '1080P': (1920, 1080),
                '720P':  (1280, 720),
                }[value.strip().upper()]
        except KeyError:
            w, h = (int(i.strip()) for i in value.upper().split('X', 1))
    else:
        try:
            w, h = value
        except (TypeError, ValueError):
            raise PiCameraValueError("Invalid resolution tuple: %r" % value)
    return PiResolution(w, h)


def to_fraction(value, den_limit=65536):
    """
    Converts *value*, which can be any numeric type, an MMAL_RATIONAL_T, or a
    (numerator, denominator) tuple to a :class:`~fractions.Fraction` limiting
    the denominator to the range 0 < n <= *den_limit* (which defaults to
    65536).
    """
    try:
        # int, long, or fraction
        n, d = value.numerator, value.denominator
    except AttributeError:
        try:
            # float
            n, d = value.as_integer_ratio()
        except AttributeError:
            try:
                n, d = value.num, value.den
            except AttributeError:
                try:
                    # tuple
                    n, d = value
                    warnings.warn(
                        PiCameraDeprecated(
                            "Setting framerate or gains as a tuple is "
                            "deprecated; please use one of Python's many "
                            "numeric classes like int, float, Decimal, or "
                            "Fraction instead"))
                except (TypeError, ValueError):
                    # try and convert anything else to a Fraction directly
                    value = Fraction(value)
                    n, d = value.numerator, value.denominator
    # Ensure denominator is reasonable
    if d == 0:
        raise PiCameraValueError("Denominator cannot be 0")
    elif d > den_limit:
        return Fraction(n, d).limit_denominator(den_limit)
    else:
        return Fraction(n, d)


def to_rational(value):
    """
    Converts *value* to an MMAL_RATIONAL_T.
    """
    value = to_fraction(value)
    return mmal.MMAL_RATIONAL_T(value.numerator, value.denominator)


def debug_pipeline(port):
    """
    Given an :class:`MMALVideoPort` *port*, this traces all objects in the
    pipeline feeding it (including components and connections) and yields each
    object in turn. Hence the generator typically yields something like:

    * :class:`MMALVideoPort` (the specified output port)
    * :class:`MMALEncoder` (the encoder which owns the output port)
    * :class:`MMALVideoPort` (the encoder's input port)
    * :class:`MMALConnection` (the connection between the splitter and encoder)
    * :class:`MMALVideoPort` (the splitter's output port)
    * :class:`MMALSplitter` (the splitter on the camera's video port)
    * :class:`MMALVideoPort` (the splitter's input port)
    * :class:`MMALConnection` (the connection between the splitter and camera)
    * :class:`MMALVideoPort` (the camera's video port)
    * :class:`MMALCamera` (the camera component)
    """

    def find_port(addr):
        for obj in MMALObject.REGISTRY:
            if isinstance(obj, MMALControlPort):
                if ct.addressof(obj._port[0]) == addr:
                    return obj
        raise IndexError('unable to locate port with address %x' % addr)

    def find_component(addr):
        for obj in MMALObject.REGISTRY:
            if isinstance(obj, MMALBaseComponent):
                if ct.addressof(obj._component[0]) == addr:
                    return obj
        raise IndexError('unable to locate component with address %x' % addr)

    assert isinstance(port, (MMALControlPort, MMALPythonPort))
    while True:
        if port.type == mmal.MMAL_PORT_TYPE_OUTPUT:
            yield port
        if isinstance(port, MMALPythonPort):
            comp = port._owner
        else:
            comp = find_component(ct.addressof(port._port[0].component[0]))
        yield comp
        if not isinstance(comp, (MMALComponent, MMALPythonComponent)):
            break
        if comp.connection is None:
            break
        if isinstance(comp.connection, MMALPythonConnection):
            port = comp.connection._target
        else:
            port = find_port(ct.addressof(comp.connection._connection[0].in_[0]))
        yield port
        yield comp.connection
        if isinstance(comp.connection, MMALPythonConnection):
            port = comp.connection._source
        else:
            port = find_port(ct.addressof(comp.connection._connection[0].out[0]))


def print_pipeline(port):
    """
    Prints a human readable representation of the pipeline feeding the
    specified :class:`MMALVideoPort` *port*.
    """
    rows = [[], [], [], [], []]
    under_comp = False
    for obj in reversed(list(debug_pipeline(port))):
        if isinstance(obj, (MMALBaseComponent, MMALPythonBaseComponent)):
            rows[0].append(obj.name)
            under_comp = True
        elif isinstance(obj, MMALVideoPort):
            rows[0].append('[%d]' % obj._port[0].index)
            if under_comp:
                rows[1].append('encoding')
            if obj.format == mmal.MMAL_ENCODING_OPAQUE:
                rows[1].append(obj.opaque_subformat)
            else:
                rows[1].append(str(obj._port[0].format[0].encoding))
            if under_comp:
                rows[2].append('buf')
            rows[2].append('%dx%d' % (obj._port[0].buffer_num, obj._port[0].buffer_size))
            if under_comp:
                rows[3].append('bitrate')
            rows[3].append('%dbps' % (obj._port[0].format[0].bitrate,))
            if under_comp:
                rows[4].append('frame')
                under_comp = False
            rows[4].append('%dx%d@%sfps' % (
                obj._port[0].format[0].es[0].video.width,
                obj._port[0].format[0].es[0].video.height,
                obj.framerate))
        elif isinstance(obj, MMALPythonPort):
            rows[0].append('[%d]' % obj._index)
            if under_comp:
                rows[1].append('encoding')
            if obj.format == mmal.MMAL_ENCODING_OPAQUE:
                rows[1].append(obj.opaque_subformat)
            else:
                rows[1].append(str(obj._format[0].encoding))
            if under_comp:
                rows[2].append('buf')
            rows[2].append('%dx%d' % (obj.buffer_count, obj.buffer_size))
            if under_comp:
                rows[3].append('bitrate')
            rows[3].append('%dbps' % (obj._format[0].bitrate,))
            if under_comp:
                rows[4].append('frame')
                under_comp = False
            rows[4].append('%dx%d@%sfps' % (
                obj._format[0].es[0].video.width,
                obj._format[0].es[0].video.height,
                obj.framerate))
        elif isinstance(obj, (MMALConnection, MMALPythonConnection)):
            rows[0].append('')
            rows[1].append('')
            rows[2].append('-->')
            rows[3].append('')
            rows[4].append('')
    if under_comp:
        rows[1].append('encoding')
        rows[2].append('buf')
        rows[3].append('bitrate')
        rows[4].append('frame')
    cols = list(zip(*rows))
    max_lens = [max(len(s) for s in col) + 2 for col in cols]
    rows = [
        ''.join('{0:{align}{width}s}'.format(s, align=align, width=max_len)
            for s, max_len, align in zip(row, max_lens, cycle('^<^>')))
        for row in rows
        ]
    for row in rows:
        print(row)


class MMALObject(object):
    """
    Represents an object wrapper around an MMAL object (component, port,
    connection, etc). This base class maintains a registry of all MMAL objects
    currently alive (via weakrefs) which permits object lookup by name and
    listing all used MMAL objects.
    """

    __slots__ = ('__weakref__',)
    REGISTRY = weakref.WeakSet()

    def __init__(self):
        super(MMALObject, self).__init__()
        MMALObject.REGISTRY.add(self)


class MMALBaseComponent(MMALObject):
    """
    Represents a generic MMAL component. Class attributes are read to determine
    the component type, and the OPAQUE sub-formats of each connectable port.
    """

    __slots__ = ('_component', '_control', '_inputs', '_outputs')
    component_type = 'none'
    opaque_input_subformats = ()
    opaque_output_subformats = ()

    def __init__(self):
        super(MMALBaseComponent, self).__init__()
        self._component = ct.POINTER(mmal.MMAL_COMPONENT_T)()
        mmal_check(
            mmal.mmal_component_create(self.component_type, self._component),
            prefix="Failed to create MMAL component %s" % self.component_type)
        if self._component[0].input_num != len(self.opaque_input_subformats):
            raise PiCameraRuntimeError(
                'Expected %d inputs but found %d on component %s' % (
                    len(self.opaque_input_subformats),
                    self._component[0].input_num,
                    self.component_type))
        if self._component[0].output_num != len(self.opaque_output_subformats):
            raise PiCameraRuntimeError(
                'Expected %d outputs but found %d on component %s' % (
                    len(self.opaque_output_subformats),
                    self._component[0].output_num,
                    self.component_type))
        self._control = MMALControlPort(self._component[0].control)
        port_class = {
            mmal.MMAL_ES_TYPE_UNKNOWN:    MMALPort,
            mmal.MMAL_ES_TYPE_CONTROL:    MMALControlPort,
            mmal.MMAL_ES_TYPE_VIDEO:      MMALVideoPort,
            mmal.MMAL_ES_TYPE_AUDIO:      MMALAudioPort,
            mmal.MMAL_ES_TYPE_SUBPICTURE: MMALSubPicturePort,
            }
        self._inputs = tuple(
            port_class[self._component[0].input[n][0].format[0].type](
                self._component[0].input[n], opaque_subformat)
            for n, opaque_subformat in enumerate(self.opaque_input_subformats))
        self._outputs = tuple(
            port_class[self._component[0].output[n][0].format[0].type](
                self._component[0].output[n], opaque_subformat)
            for n, opaque_subformat in enumerate(self.opaque_output_subformats))

    def close(self):
        """
        Close the component and release all its resources. After this is
        called, most methods will raise exceptions if called.
        """
        if self._component is not None:
            # ensure we free any pools associated with input/output ports
            for output in self.outputs:
                output.disable()
            for input in self.inputs:
                input.disable()
            mmal.mmal_component_destroy(self._component)
            self._component = None
            self._inputs = ()
            self._outputs = ()
            self._control = None

    @property
    def name(self):
        return self._component[0].name.decode('ascii')

    @property
    def control(self):
        """
        The :class:`MMALControlPort` control port of the component which can be
        used to configure most aspects of the component's behaviour.
        """
        return self._control

    @property
    def inputs(self):
        """
        A sequence of :class:`MMALPort` objects representing the inputs
        of the component.
        """
        return self._inputs

    @property
    def outputs(self):
        """
        A sequence of :class:`MMALPort` objects representing the outputs
        of the component.
        """
        return self._outputs

    @property
    def enabled(self):
        """
        Returns ``True`` if the component is currently enabled. Use
        :meth:`enable` and :meth:`disable` to control the component's state.
        """
        return bool(self._component[0].is_enabled)

    def enable(self):
        """
        Enable the component. When a component is enabled it will process data
        sent to its input port(s), sending the results to buffers on its output
        port(s). Components may be implicitly enabled by connections.
        """
        mmal_check(
            mmal.mmal_component_enable(self._component),
            prefix="Failed to enable component")

    def disable(self):
        """
        Disables the component.
        """
        mmal_check(
            mmal.mmal_component_disable(self._component),
            prefix="Failed to disable component")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def __repr__(self):
        if self._component is not None:
            return '<%s "%s": %d inputs %d outputs>' % (
                self.__class__.__name__, self.name,
                len(self.inputs), len(self.outputs))
        else:
            return '<%s closed>' % self.__class__.__name__


class MMALControlPort(MMALObject):
    """
    Represents an MMAL port with properties to configure the port's parameters.
    """
    __slots__ = ('_port', '_params', '_wrapper')

    def __init__(self, port):
        super(MMALControlPort, self).__init__()
        self._port = port
        self._params = MMALPortParams(port)
        self._wrapper = None

    @property
    def index(self):
        """
        Returns an integer indicating the port's position within its owning
        list (inputs, outputs, etc.)
        """
        return self._port[0].index

    @property
    def enabled(self):
        """
        Returns a :class:`bool` indicating whether the port is currently
        enabled. Unlike other classes, this is a read-only property. Use
        :meth:`enable` and :meth:`disable` to modify the value.
        """
        return bool(self._port[0].is_enabled)

    def enable(self, callback=None):
        """
        Enable the port with the specified callback function (this must be
        ``None`` for connected ports, and a callable for disconnected ports).

        The callback function must accept two parameters which will be this
        :class:`MMALControlPort` (or descendent) and an :class:`MMALBuffer`
        instance. Any return value will be ignored.
        """
        def wrapper(port, buf):
            buf = MMALBuffer(buf)
            try:
                callback(self, buf)
            finally:
                buf.release()

        if callback:
            self._wrapper = mmal.MMAL_PORT_BH_CB_T(wrapper)
        else:
            self._wrapper = None
        mmal_check(
            mmal.mmal_port_enable(self._port, self._wrapper),
            prefix="Unable to enable port %s" % self.name)

    def disable(self):
        """
        Disable the port.
        """
        # NOTE: The test here only exists to avoid spamming the console; when
        # disabling an already disabled port MMAL dumps errors to stderr. If
        # this test isn't here closing a camera results in half a dozen lines
        # of ignored errors
        if self.enabled:
            try:
                mmal_check(
                    mmal.mmal_port_disable(self._port),
                    prefix="Unable to disable port %s" % self.name)
            except PiCameraMMALError as e:
                # Ignore the error if we're disabling an already disabled port
                if not (e.status == mmal.MMAL_EINVAL and not self.enabled):
                    raise e
        self._wrapper = None

    @property
    def name(self):
        return self._port[0].name.decode('ascii')

    @property
    def type(self):
        """
        The type of the port. One of:

        * MMAL_PORT_TYPE_OUTPUT
        * MMAL_PORT_TYPE_INPUT
        * MMAL_PORT_TYPE_CONTROL
        * MMAL_PORT_TYPE_CLOCK
        """
        return self._port[0].type

    @property
    def capabilities(self):
        """
        The capabilities of the port. A bitfield of the following:

        * MMAL_PORT_CAPABILITY_PASSTHROUGH
        * MMAL_PORT_CAPABILITY_ALLOCATION
        * MMAL_PORT_CAPABILITY_SUPPORTS_EVENT_FORMAT_CHANGE
        """
        return self._port[0].capabilities

    @property
    def params(self):
        """
        The configurable parameters for the port. This is presented as a
        mutable mapping of parameter numbers to values, implemented by the
        :class:`MMALPortParams` class.
        """
        return self._params

    def __repr__(self):
        if self._port is not None:
            return '<MMALControlPort "%s">' % self.name
        else:
            return '<MMALControlPort closed>'


class MMALPort(MMALControlPort):
    """
    Represents an MMAL port with properties to configure and update the port's
    format. This is the base class of :class:`MMALVideoPort`,
    :class:`MMALAudioPort`, and :class:`MMALSubPicturePort`.
    """
    __slots__ = ('_opaque_subformat', '_pool', '_stopped')

    def __init__(self, port, opaque_subformat='OPQV'):
        super(MMALPort, self).__init__(port)
        self.opaque_subformat = opaque_subformat
        self._pool = None
        self._stopped = True

    def _get_opaque_subformat(self):
        return self._opaque_subformat
    def _set_opaque_subformat(self, value):
        self._opaque_subformat = value
    opaque_subformat = property(
        _get_opaque_subformat, _set_opaque_subformat, doc="""\
        Retrieves or sets the opaque sub-format that the port speaks. While
        most formats (I420, RGBA, etc.) mean one thing, the opaque format is
        special; different ports produce different sorts of data when
        configured for OPQV format. This property stores a string which
        uniquely identifies what the associated port means for OPQV format.

        If the port does not support opaque format at all, set this property to
        ``None``.

        :class:`MMALConnection` uses this information when negotiating formats
        for a connection between two ports.
        """)

    def _get_format(self):
        result = self._port[0].format[0].encoding
        if FIX_RGB_BGR_ORDER:
            return {
                mmal.MMAL_ENCODING_RGB24: mmal.MMAL_ENCODING_BGR24,
                mmal.MMAL_ENCODING_BGR24: mmal.MMAL_ENCODING_RGB24,
                }.get(result.value, result)
        else:
            return result
    def _set_format(self, value):
        if FIX_RGB_BGR_ORDER:
            value = {
                mmal.MMAL_ENCODING_RGB24: mmal.MMAL_ENCODING_BGR24,
                mmal.MMAL_ENCODING_BGR24: mmal.MMAL_ENCODING_RGB24,
                }.get(value, value)
        self._port[0].format[0].encoding = value
        if value == mmal.MMAL_ENCODING_OPAQUE:
            self._port[0].format[0].encoding_variant = mmal.MMAL_ENCODING_I420
    format = property(_get_format, _set_format, doc="""\
        Retrieves or sets the encoding format of the port. Setting this
        attribute implicitly sets the encoding variant to a sensible value
        (I420 in the case of OPAQUE).

        After setting this attribute, call :meth:`commit` to make the changes
        effective.
        """)

    @property
    def supported_formats(self):
        """
        Retrieves a sequence of supported encodings on this port.

        .. warning::

            On older firmwares, property does not work on the camera's still
            port (``MMALCamera.outputs[2]``) due to an underlying bug.
        """
        mp = self.params[mmal.MMAL_PARAMETER_SUPPORTED_ENCODINGS]
        return [
            mmal.MMAL_FOURCC_T(v)
            for v in mp.encoding
            if v != 0
            ][:mp.hdr.size // ct.sizeof(ct.c_uint32)]

    def _get_bitrate(self):
        return self._port[0].format[0].bitrate
    def _set_bitrate(self, value):
        self._port[0].format[0].bitrate = value
    bitrate = property(_get_bitrate, _set_bitrate, doc="""\
        Retrieves or sets the bitrate limit for the port's format.
        """)

    def copy_from(self, source):
        """
        Copies the port's :attr:`format` from the *source*
        :class:`MMALControlPort`.
        """
        if isinstance(source, MMALPythonPort):
            mmal.mmal_format_copy(self._port[0].format, source._format)
        else:
            mmal.mmal_format_copy(self._port[0].format, source._port[0].format)

    def commit(self):
        """
        Commits the port's configuration and automatically updates the number
        and size of associated buffers according to the recommendations of the
        MMAL library. This is typically called after adjusting the port's
        format and/or associated settings (like width and height for video
        ports).
        """
        mmal_check(
            mmal.mmal_port_format_commit(self._port),
            prefix="Format couldn't be set on port %s" % self.name)
        # Workaround: Unfortunately, there is an upstream issue with the
        # buffer_num_recommended which means it can't currently be used (see
        # discussion in raspberrypi/userland#167). There's another upstream
        # issue with buffer_num_min which means we need to guard against 0
        # values...
        self._port[0].buffer_num = max(1, self._port[0].buffer_num_min)
        self._port[0].buffer_size = (
            self._port[0].buffer_size_recommended
            if self._port[0].buffer_size_recommended > 0 else
            self._port[0].buffer_size_min)

    @property
    def pool(self):
        """
        Returns the :class:`MMALPool` associated with the buffer, if any.
        """
        return self._pool

    def get_buffer(self, block=True, timeout=None):
        """
        Returns a :class:`MMALBuffer` from the associated :attr:`pool`. *block*
        and *timeout* act as they do in the corresponding
        :meth:`MMALPool.get_buffer`.
        """
        return self.pool.get_buffer(block, timeout)

    def send_buffer(self, buf):
        """
        Send :class:`MMALBuffer` *buf* to the port.
        """
        mmal_check(
            mmal.mmal_port_send_buffer(self._port, buf._buf),
            prefix="unable to send the buffer to port %s" % self.name)

    def flush(self):
        """
        Flush the port.
        """
        mmal_check(
            mmal.mmal_port_flush(self._port),
            prefix="Unable to flush port %s" % self.name)

    def _get_buffer_count(self):
        return self._port[0].buffer_num
    def _set_buffer_count(self, value):
        if value < 1:
            raise PiCameraMMALError(mmal.MMAL_EINVAL, 'buffer count <1')
        self._port[0].buffer_num = value
    buffer_count = property(_get_buffer_count, _set_buffer_count, doc="""\
        The number of buffers allocated (or to be allocated) to the port.
        The ``mmalobj`` layer automatically configures this based on
        recommendations from the MMAL library.
        """)

    def _get_buffer_size(self):
        return self._port[0].buffer_size
    def _set_buffer_size(self, value):
        if value < 0:
            raise PiCameraMMALError(mmal.MMAL_EINVAL, 'buffer size <0')
        self._port[0].buffer_size = value
    buffer_size = property(_get_buffer_size, _set_buffer_size, doc="""\
        The size of buffers allocated (or to be allocated) to the port. The
        size of buffers is typically dictated by the port's format. The
        ``mmalobj`` layer automatically configures this based on
        recommendations from the MMAL library.
        """)

    def enable(self, callback=None):
        """
        Enable the port with the specified callback function (this must be
        ``None`` for connected ports, and a callable for disconnected ports).

        The callback function must accept two parameters which will be this
        :class:`MMALControlPort` (or descendent) and an :class:`MMALBuffer`
        instance. The callback should return ``True`` when processing is
        complete and no further calls are expected (e.g. at frame-end for an
        image encoder), and ``False`` otherwise.
        """
        def wrapper(port, buf):
            buf = MMALBuffer(buf)
            try:
                if not self._stopped and callback(self, buf):
                    self._stopped = True
            finally:
                buf.release()
                while not self._stopped:
                    try:
                        self._pool.send_buffer(timeout=0.01)
                    except PiCameraMMALError as e:
                        if e.status != mmal.MMAL_EAGAIN:
                            raise
                    else:
                        break

        # Workaround: There is a bug in the MJPEG encoder that causes a
        # deadlock if the FIFO is full on shutdown. Increasing the encoder
        # buffer size makes this less likely to happen. See
        # raspberrypi/userland#208. Connecting the encoder component resets the
        # output port's buffer size, hence why we correct this here, just
        # before enabling the port.
        if self._port[0].format[0].encoding == mmal.MMAL_ENCODING_MJPEG:
            self._port[0].buffer_size = max(512 * 1024, self._port[0].buffer_size_recommended)
        if callback:
            assert self._stopped
            self._stopped = False
            self._wrapper = mmal.MMAL_PORT_BH_CB_T(wrapper)
            mmal_check(
                mmal.mmal_port_enable(self._port, self._wrapper),
                prefix="Unable to enable port %s" % self.name)
            assert self._pool is None
            self._pool = MMALPortPool(self)
            # If this port is an output port, send it all the buffers
            # in the pool. If it's an input port, don't bother: the user
            # will presumably want to feed buffers to it manually
            if self._port[0].type == mmal.MMAL_PORT_TYPE_OUTPUT:
                try:
                    self._pool.send_all_buffers(False)
                except:
                    self._pool.close()
                    self._pool = None
                    raise
        else:
            super(MMALPort, self).enable()

    def disable(self):
        """
        Disable the port.
        """
        self._stopped = True
        super(MMALPort, self).disable()
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def __repr__(self):
        if self._port is not None:
            return '<MMALPort "%s": format=%r buffers=%dx%d>' % (
                self.name, self.format, self.buffer_count, self.buffer_size)
        else:
            return '<MMALPort closed>'


class MMALVideoPort(MMALPort):
    """
    Represents an MMAL port used to pass video data.
    """
    __slots__ = ()

    def _get_framesize(self):
        return PiResolution(
            self._port[0].format[0].es[0].video.crop.width,
            self._port[0].format[0].es[0].video.crop.height,
            )
    def _set_framesize(self, value):
        value = to_resolution(value)
        video = self._port[0].format[0].es[0].video
        video.width = bcm_host.VCOS_ALIGN_UP(value.width, 32)
        video.height = bcm_host.VCOS_ALIGN_UP(value.height, 16)
        video.crop.width = value.width
        video.crop.height = value.height
    framesize = property(_get_framesize, _set_framesize, doc="""\
        Retrieves or sets the size of the port's video frames as a (width,
        height) tuple. This attribute implicitly handles scaling the given
        size up to the block size of the camera (32x16).

        After setting this attribute, call :meth:`~MMALPort.commit` to make the
        changes effective.
        """)

    def _get_framerate(self):
        video = self._port[0].format[0].es[0].video
        try:
            return Fraction(
                video.frame_rate.num,
                video.frame_rate.den)
        except ZeroDivisionError:
            assert video.frame_rate.num == 0
            return Fraction(0, 1)
    def _set_framerate(self, value):
        value = to_fraction(value)
        video = self._port[0].format[0].es[0].video
        video.frame_rate.num = value.numerator
        video.frame_rate.den = value.denominator
    framerate = property(_get_framerate, _set_framerate, doc="""\
        Retrieves or sets the framerate of the port's video frames in fps.

        After setting this attribute, call :meth:`~MMALPort.commit` to make the
        changes effective.
        """)

    def __repr__(self):
        if self._port is not None:
            return '<MMALVideoPort "%s": format=%r buffers=%dx%d frames=%s@%sfps>' % (
                self.name, self.format, self._port[0].buffer_num,
                self._port[0].buffer_size, self.framesize, self.framerate)
        else:
            return '<MMALVideoPort closed>'


class MMALAudioPort(MMALPort):
    """
    Represents an MMAL port used to pass audio data.
    """
    __slots__ = ()

    def __repr__(self):
        if self._port is not None:
            return '<MMALAudioPort "%s": format=%r buffers=%dx%d>' % (
                self.name, self.format, self._port[0].buffer_num,
                self._port[0].buffer_size)
        else:
            return '<MMALAudioPort closed>'


class MMALSubPicturePort(MMALPort):
    """
    Represents an MMAL port used to pass sub-picture (caption) data.
    """
    __slots__ = ()

    def __repr__(self):
        if self._port is not None:
            return '<MMALSubPicturePort "%s": format=%r buffers=%dx%d>' % (
                self.name, self.format, self._port[0].buffer_num,
                self._port[0].buffer_size)
        else:
            return '<MMALSubPicturePort closed>'


class MMALPortParams(object):
    """
    Represents the parameters of an MMAL port. This class implements the
    :attr:`MMALControlPort.params` attribute.

    Internally, the class understands how to convert certain structures to more
    common Python data-types. For example, parameters that expect an
    MMAL_RATIONAL_T type will return and accept Python's
    :class:`~fractions.Fraction` class (or any other numeric types), while
    parameters that expect an MMAL_BOOL_T type will treat anything as a truthy
    value. Parameters that expect the MMAL_PARAMETER_STRING_T structure will be
    treated as plain strings, and likewise MMAL_PARAMETER_INT32_T and similar
    structures will be treated as plain ints.

    Parameters that expect more complex structures will return and expect
    those structures verbatim.
    """
    __slots__ = ('_port',)

    def __init__(self, port):
        super(MMALPortParams, self).__init__()
        self._port = port

    def __getitem__(self, key):
        dtype = PARAM_TYPES[key]
        # Use the short-cut functions where possible (teeny bit faster if we
        # get some C to do the structure wrapping for us)
        func = {
            mmal.MMAL_PARAMETER_RATIONAL_T: mmal.mmal_port_parameter_get_rational,
            mmal.MMAL_PARAMETER_BOOLEAN_T:  mmal.mmal_port_parameter_get_boolean,
            mmal.MMAL_PARAMETER_INT32_T:    mmal.mmal_port_parameter_get_int32,
            mmal.MMAL_PARAMETER_INT64_T:    mmal.mmal_port_parameter_get_int64,
            mmal.MMAL_PARAMETER_UINT32_T:   mmal.mmal_port_parameter_get_uint32,
            mmal.MMAL_PARAMETER_UINT64_T:   mmal.mmal_port_parameter_get_uint64,
            }.get(dtype, mmal.mmal_port_parameter_get)
        conv = {
            mmal.MMAL_PARAMETER_RATIONAL_T: lambda v: Fraction(v.num, v.den),
            mmal.MMAL_PARAMETER_BOOLEAN_T:  lambda v: v.value != mmal.MMAL_FALSE,
            mmal.MMAL_PARAMETER_INT32_T:    lambda v: v.value,
            mmal.MMAL_PARAMETER_INT64_T:    lambda v: v.value,
            mmal.MMAL_PARAMETER_UINT32_T:   lambda v: v.value,
            mmal.MMAL_PARAMETER_UINT64_T:   lambda v: v.value,
            mmal.MMAL_PARAMETER_STRING_T:   lambda v: v.str.decode('ascii'),
            }.get(dtype, lambda v: v)
        if func == mmal.mmal_port_parameter_get:
            result = dtype(
                mmal.MMAL_PARAMETER_HEADER_T(key, ct.sizeof(dtype))
                )
            mmal_check(
                func(self._port, result.hdr),
                prefix="Failed to get parameter %d" % key)
        else:
            dtype = {
                mmal.MMAL_PARAMETER_RATIONAL_T: mmal.MMAL_RATIONAL_T,
                mmal.MMAL_PARAMETER_BOOLEAN_T:  mmal.MMAL_BOOL_T,
                mmal.MMAL_PARAMETER_INT32_T:    ct.c_int32,
                mmal.MMAL_PARAMETER_INT64_T:    ct.c_int64,
                mmal.MMAL_PARAMETER_UINT32_T:   ct.c_uint32,
                mmal.MMAL_PARAMETER_UINT64_T:   ct.c_uint64,
                }[dtype]
            result = dtype()
            mmal_check(
                func(self._port, key, result),
                prefix="Failed to get parameter %d" % key)
        return conv(result)

    def __setitem__(self, key, value):
        dtype = PARAM_TYPES[key]
        func = {
            mmal.MMAL_PARAMETER_RATIONAL_T: mmal.mmal_port_parameter_set_rational,
            mmal.MMAL_PARAMETER_BOOLEAN_T:  mmal.mmal_port_parameter_set_boolean,
            mmal.MMAL_PARAMETER_INT32_T:    mmal.mmal_port_parameter_set_int32,
            mmal.MMAL_PARAMETER_INT64_T:    mmal.mmal_port_parameter_set_int64,
            mmal.MMAL_PARAMETER_UINT32_T:   mmal.mmal_port_parameter_set_uint32,
            mmal.MMAL_PARAMETER_UINT64_T:   mmal.mmal_port_parameter_set_uint64,
            mmal.MMAL_PARAMETER_STRING_T:   mmal.mmal_port_parameter_set_string,
            }.get(dtype, mmal.mmal_port_parameter_set)
        conv = {
            mmal.MMAL_PARAMETER_RATIONAL_T: lambda v: to_rational(v),
            mmal.MMAL_PARAMETER_BOOLEAN_T:  lambda v: mmal.MMAL_TRUE if v else mmal.MMAL_FALSE,
            mmal.MMAL_PARAMETER_STRING_T:   lambda v: v.encode('ascii'),
            }.get(dtype, lambda v: v)
        if func == mmal.mmal_port_parameter_set:
            mp = conv(value)
            assert mp.hdr.id == key
            assert mp.hdr.size >= ct.sizeof(dtype)
            mmal_check(
                func(self._port, mp.hdr),
                prefix="Failed to set parameter %d to %r" % (key, value))
        else:
            mmal_check(
                func(self._port, key, conv(value)),
                prefix="Failed to set parameter %d to %r" % (key, value))


class MMALBuffer(object):
    """
    Represents an MMAL buffer header. This is usually constructed from the
    buffer header pointer and is largely supplied to make working with
    the buffer's data a bit simpler. Using the buffer as a context manager
    implicitly locks the buffer's memory and returns the :mod:`ctypes`
    buffer object itself::

        def callback(port, buf):
            with buf as data:
                # data is a ctypes uint8 array with size entries
                print(len(data))

    Alternatively you can use the :attr:`data` property directly, which returns
    and modifies the buffer's data as a :class:`bytes` object. However, beware
    that you must still use the buffer as a context manager if you wish to
    lock the buffer's memory (generally required when dealing with VideoCore
    buffers)::

        def callback(port, buf):
            with buf:
                # the buffer contents as a byte-string
                print(buf.data)
    """
    __slots__ = ('_buf',)

    def __init__(self, buf):
        super(MMALBuffer, self).__init__()
        self._buf = buf

    def _get_command(self):
        return self._buf[0].cmd
    def _set_command(self, value):
        self._buf[0].cmd = value
    command = property(_get_command, _set_command, doc="""\
        The command set in the buffer's meta-data. This is usually 0 for
        buffers returned by an encoder; typically this is only used by buffers
        sent to the callback of a control port.
        """)

    def _get_flags(self):
        return self._buf[0].flags
    def _set_flags(self, value):
        self._buf[0].flags = value
    flags = property(_get_flags, _set_flags, doc="""\
        The flags set in the buffer's meta-data, returned as a bitmapped
        integer. Typical flags include:

        * ``MMAL_BUFFER_HEADER_FLAG_EOS`` -- end of stream
        * ``MMAL_BUFFER_HEADER_FLAG_FRAME_START`` -- start of frame data
        * ``MMAL_BUFFER_HEADER_FLAG_FRAME_END`` -- end of frame data
        * ``MMAL_BUFFER_HEADER_FLAG_KEYFRAME`` -- frame is a key-frame
        * ``MMAL_BUFFER_HEADER_FLAG_FRAME`` -- frame data
        * ``MMAL_BUFFER_HEADER_FLAG_CODECSIDEINFO`` -- motion estimatation data
        """)

    def _get_pts(self):
        return self._buf[0].pts
    def _set_pts(self, value):
        self._buf[0].pts = value
    pts = property(_get_pts, _set_pts, doc="""\
        The presentation timestamp (PTS) of the buffer, as an integer number
        of microseconds or ``MMAL_TIME_UNKNOWN``.
        """)

    def _get_dts(self):
        return self._buf[0].dts
    def _set_dts(self, value):
        self._buf[0].dts = value
    dts = property(_get_dts, _set_dts, doc="""\
        The decoding timestamp (DTS) of the buffer, as an integer number of
        microseconds or ``MMAL_TIME_UNKNOWN``.
        """)

    @property
    def size(self):
        """
        Returns the length of the buffer's data area in bytes. This will be
        greater than or equal to :attr:`length` and is fixed in value.
        """
        return self._buf[0].alloc_size

    def _get_offset(self):
        return self._buf[0].offset
    def _set_offset(self, value):
        assert 0 <= value <= self.size
        self._buf[0].offset = value
        self.length = min(self.size - self.offset, self.length)
    offset = property(_get_offset, _set_offset, doc="""\
        The offset from the start of the buffer at which the data actually
        begins. Defaults to 0. If this is set to a value which would force the
        current :attr:`length` off the end of the buffer's :attr:`size`, then
        :attr:`length` will be decreased automatically.
        """)

    def _get_length(self):
        return self._buf[0].length
    def _set_length(self, value):
        assert 0 <= value <= self.size - self.offset
        self._buf[0].length = value
    length = property(_get_length, _set_length, doc="""\
        The length of data held in the buffer. Must be less than or equal to
        the allocated size of data held in :attr:`size` minus the data
        :attr:`offset`. This attribute can be used to effectively blank the
        buffer by setting it to zero.
        """)

    def _get_data(self):
        with self as buf:
            return ct.string_at(
                ct.byref(buf, self._buf[0].offset),
                self._buf[0].length)
    def _set_data(self, value):
        if isinstance(value, memoryview) and (value.ndim > 1 or value.itemsize > 1):
            value = value.cast('B')
        data_len = len(value)
        if data_len:
            assert data_len <= self.size
            bp = ct.c_uint8 * data_len
            try:
                sp = bp.from_buffer(value)
            except TypeError:
                sp = bp.from_buffer_copy(value)
            with self as buf:
                ct.memmove(buf, sp, data_len)
        self._buf[0].offset = 0
        self._buf[0].length = data_len
    data = property(_get_data, _set_data, doc="""\
        The data held in the buffer as a :class:`bytes` string. You can set
        this attribute to modify the data in the buffer. Acceptable values
        are anything that supports the buffer protocol, and which contains
        :attr:`size` bytes or less. Setting this attribute implicitly modifies
        the :attr:`length` attribute to the length of the specified value and
        sets :attr:`offset` to zero.

        .. note::

            Accessing a buffer's data via this attribute is relatively slow
            (as it copies the buffer's data to/from Python objects). See the
            :class:`MMALBuffer` documentation for details of a faster (but
            more complex) method.
        """)

    def replicate(self, source):
        """
        Replicates the *source* :class:`MMALBuffer`. This copies all fields
        from the *source* buffer, including the internal :attr:`data` pointer.
        In other words, after replication this buffer and the *source* buffer
        will share the same block of memory for *data*.

        The *source* buffer will also be referenced internally by this buffer
        and will only be recycled once this buffer is released.

        .. note::

            This is fundamentally different to the operation of the
            :meth:`copy_from` method.
        """
        mmal_check(
            mmal.mmal_buffer_header_replicate(self._buf, source._buf),
            prefix='unable to replicate buffer')

    def copy_from(self, source):
        """
        Copies all fields (including data) from the *source*
        :class:`MMALBuffer`. This buffer must have sufficient :attr:`size` to
        store :attr:`length` bytes from the *source* buffer. This method
        implicitly sets :attr:`offset` to zero, the :attr:`length` to the
        number of bytes copied.

        .. note::

            This is fundamentally different to the operation of the
            :meth:`replicate` method.
        """
        assert self.size >= source.length
        source_len = source._buf[0].length
        if source_len:
            with self as target_buf, source as source_buf:
                ct.memmove(target_buf, ct.byref(source_buf, source.offset), source_len)
        self._buf[0].offset = 0
        self._buf[0].length = source_len
        self.copy_meta(source)

    def copy_meta(self, source):
        """
        Copy meta-data from the *source* :class:`MMALBuffer`; specifically this
        copies all buffer fields with the exception of :attr:`data`,
        :attr:`length` and :attr:`offset`.
        """
        self._buf[0].cmd = source._buf[0].cmd
        self._buf[0].flags = source._buf[0].flags
        self._buf[0].dts = source._buf[0].dts
        self._buf[0].pts = source._buf[0].pts
        self._buf[0].type[0] = source._buf[0].type[0]

    def acquire(self):
        """
        Acquire a reference to the buffer. This will prevent the buffer from
        being recycled until :meth:`release` is called. This method can be
        called multiple times in which case an equivalent number of calls
        to :meth:`release` must be made before the buffer will actually be
        released.
        """
        mmal.mmal_buffer_header_acquire(self._buf)

    def release(self):
        """
        Release a reference to the buffer. This is the opposing call to
        :meth:`acquire`. Once all references have been released, the buffer
        will be recycled.
        """
        mmal.mmal_buffer_header_release(self._buf)

    def reset(self):
        """
        Resets all buffer header fields to default values.
        """
        mmal.mmal_buffer_header_reset(self._buf)

    def __enter__(self):
        mmal_check(
            mmal.mmal_buffer_header_mem_lock(self._buf),
            prefix='unable to lock buffer header memory')
        return ct.cast(
            self._buf[0].data,
            ct.POINTER(ct.c_uint8 * self._buf[0].alloc_size)).contents

    def __exit__(self, *exc):
        mmal.mmal_buffer_header_mem_unlock(self._buf)
        return False

    def __repr__(self):
        if self._buf is not None:
            return '<MMALBuffer object: flags=%s command=%s length=%d>' % (
                ''.join((
                'S' if self.flags & mmal.MMAL_BUFFER_HEADER_FLAG_FRAME_START   else '_',
                'E' if self.flags & mmal.MMAL_BUFFER_HEADER_FLAG_FRAME_END     else '_',
                'K' if self.flags & mmal.MMAL_BUFFER_HEADER_FLAG_KEYFRAME      else '_',
                'C' if self.flags & mmal.MMAL_BUFFER_HEADER_FLAG_CONFIG        else '_',
                'M' if self.flags & mmal.MMAL_BUFFER_HEADER_FLAG_CODECSIDEINFO else '_',
                'X' if self.flags & mmal.MMAL_BUFFER_HEADER_FLAG_EOS           else '_',
                )), {
                0: 'none',
                mmal.MMAL_EVENT_ERROR:             'error',
                mmal.MMAL_EVENT_FORMAT_CHANGED:    'format-change',
                mmal.MMAL_EVENT_PARAMETER_CHANGED: 'param-change',
                mmal.MMAL_EVENT_EOS:               'end-of-stream',
                }[self.command], self.length)
        else:
            return '<MMALBuffer object: ???>'


class MMALPool(object):
    """
    Represents an MMAL pool containing :class:`MMALBuffer` objects. All active
    ports are associated with a pool of buffers. Can be treated as a sequence
    of :class:`MMALBuffer` objects but this is only recommended for debugging
    purposes.
    """
    __slots__ = ('_pool',)

    def __init__(self, pool):
        self._pool = pool
        super(MMALPool, self).__init__()

    def __len__(self):
        return self._pool[0].headers_num

    def __getitem__(self, index):
        return MMALBuffer(self._pool[0].header[index])

    def close(self):
        if self._pool is not None:
            mmal.mmal_pool_destroy(self._pool)
            self._pool = None

    def resize(self, new_count, new_size):
        """
        Resizes the pool to contain *new_count* buffers with *new_size* bytes
        allocated to each buffer.

        *new_count* must be 1 or more (you cannot resize a pool to contain
        no headers). However, *new_size* can be 0 which causes all payload
        buffers to be released.

        .. warning::

            If the pool is associated with a port, the port must be disabled
            when resizing the pool.
        """
        mmal_check(
            mmal.mmal_pool_resize(self._pool, new_count, new_size),
            prefix='unable to resize pool')

    def get_buffer(self, block=True, timeout=None):
        """
        Get the next buffer from the pool. If *block* is ``True`` (the default)
        and *timeout* is ``None`` (the default) then the method will block
        until a buffer is available. Otherwise *timeout* is the maximum time to
        wait (in seconds) for a buffer to become available. If a buffer is not
        available before the timeout expires, the method returns ``None``.

        Likewise, if *block* is ``False`` and no buffer is immediately
        available then ``None`` is returned.
        """
        if block and timeout is None:
            buf = mmal.mmal_queue_wait(self._pool[0].queue)
        elif block and timeout is not None:
            buf = mmal.mmal_queue_timedwait(self._pool[0].queue, int(timeout * 1000))
        else:
            buf = mmal.mmal_queue_get(self._pool[0].queue)
        if buf:
            return MMALBuffer(buf)

    def send_buffer(self, port, block=True, timeout=None):
        """
        Get a buffer from the pool and send it to *port*. *block* and *timeout*
        act as they do in :meth:`get_buffer`. If no buffer is available (for
        the values of *block* and *timeout*, :exc:`~picamera.PiCameraMMALError`
        is raised).
        """
        buf = self.get_buffer(block, timeout)
        if buf is None:
            raise PiCameraMMALError(mmal.MMAL_EAGAIN, 'no buffers available')
        port.send_buffer(buf)

    def send_all_buffers(self, port, block=True, timeout=None):
        """
        Send all buffers from the pool to *port*. *block* and *timeout* act as
        they do in :meth:`get_buffer`. If no buffer is available (for the
        values of *block* and *timeout*, :exc:`~picamera.PiCameraMMALError` is
        raised).
        """
        for i in range(mmal.mmal_queue_length(self._pool[0].queue)):
            buf = self.get_buffer(block, timeout)
            if buf is None:
                raise PiCameraMMALError(mmal.MMAL_EAGAIN, 'no buffers available')
            port.send_buffer(buf)


class MMALPortPool(MMALPool):
    """
    Construct an MMAL pool for the number and size of buffers required by
    the :class:`MMALPort` *port*.
    """
    __slots__ = ('_port',)

    def __init__(self, port):
        pool = mmal.mmal_port_pool_create(
            port._port, port._port[0].buffer_num, port._port[0].buffer_size)
        if not pool:
            raise PiCameraMMALError(
                mmal.MMAL_ENOSPC,
                'failed to create buffer header pool for port %s' % port.name)
        super(MMALPortPool, self).__init__(pool)
        self._port = port

    def close(self):
        if self._pool is not None:
            mmal.mmal_port_pool_destroy(self._port._port, self._pool)
            self._port = None
            self._pool = None
        super(MMALPortPool, self).close()

    @property
    def port(self):
        return self._port

    def send_buffer(self, block=True, timeout=None):
        """
        Get a buffer from the pool and send it to the port the pool is
        associated with. *block* and *timeout* act as they do in
        :meth:`MMALPool.get_buffer`.
        """
        super(MMALPortPool, self).send_buffer(self._port, block, timeout)

    def send_all_buffers(self, block=True, timeout=None):
        """
        Send all buffers from the pool to the port the pool is associated with.
        *block* and *timeout* act as they do in :meth:`MMALPool.get_buffer`.
        """
        super(MMALPortPool, self).send_all_buffers(self._port, block, timeout)


class MMALConnection(MMALObject):
    """
    Represents an MMAL internal connection between two components. The
    constructor accepts arguments providing the *source* :class:`MMALPort` and
    *target* :class:`MMALPort`.

    The connection will automatically negotiate the most efficient format
    supported by both ports (implicitly handling the incompatibility of some
    OPAQUE sub-formats). See :ref:`mmal` for more information.
    """
    __slots__ = ('_connection',)

    compatible_formats = {
        (f, f) for f in (
            'OPQV-single',
            'OPQV-dual',
            'OPQV-strips',
            'I420')
        } | {
        ('OPQV-dual', 'OPQV-single'),
        ('OPQV-single', 'OPQV-dual'), # recent firmwares permit this
        }

    def __init__(self, source, target):
        super(MMALConnection, self).__init__()
        if not isinstance(source, MMALPort):
            raise PiCameraValueError('source is not an MMAL port')
        if not isinstance(target, MMALPort):
            raise PiCameraValueError('target is not an MMAL port')
        self._connection = ct.POINTER(mmal.MMAL_CONNECTION_T)()
        if (source.opaque_subformat, target.opaque_subformat) in self.compatible_formats:
            source.format = mmal.MMAL_ENCODING_OPAQUE
        else:
            source.format = mmal.MMAL_ENCODING_I420
        source.commit()
        mmal_check(
            mmal.mmal_connection_create(
                self._connection, source._port, target._port,
                mmal.MMAL_CONNECTION_FLAG_TUNNELLING |
                mmal.MMAL_CONNECTION_FLAG_ALLOCATION_ON_INPUT),
            prefix="Failed to create connection")
        mmal_check(
            mmal.mmal_connection_enable(self._connection),
            prefix="Failed to enable connection")

    def close(self):
        if self._connection is not None:
            mmal.mmal_connection_destroy(self._connection)
            self._connection = None

    @property
    def enabled(self):
        """
        Returns ``True`` if the connection is enabled. Use :meth:`enable`
        and :meth:`disable` to control the state of the connection.
        """
        return bool(self._connection[0].is_enabled)

    def enable(self):
        """
        Enable the connection. When a connection is enabled, data is
        continually transferred from the output port of the source to the input
        port of the target component.
        """
        mmal_check(
            mmal.mmal_connection_enable(self._connection),
            prefix="Failed to enable connection")

    def disable(self):
        """
        Disables the connection.
        """
        mmal_check(
            mmal.mmal_connection_disable(self._connection),
            prefix="Failed to disable connection")

    @property
    def name(self):
        return self._connection[0].name.decode('ascii')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def __repr__(self):
        if self._connection is not None:
            return '<MMALConnection "%s">' % self.name
        else:
            return '<MMALConnection closed>'


class MMALRawCamera(MMALBaseComponent):
    """
    The MMAL raw camera component.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_RAW_CAMERA
    opaque_input_subformats = ()
    opaque_output_subformats = ('OPQV-single',)


class MMALCamera(MMALBaseComponent):
    """
    Represents the MMAL camera component. This component has 0 input ports and
    3 output ports. The intended use of the output ports (which in turn
    determines the behaviour of those ports) is as follows:

    * Port 0 is intended for preview renderers

    * Port 1 is intended for video recording

    * Port 2 is intended for still image capture

    Use the ``MMAL_PARAMETER_CAMERA_CONFIG`` parameter on the control port to
    obtain and manipulate the camera's configuration.
    """
    __slots__ = ()

    component_type = mmal.MMAL_COMPONENT_DEFAULT_CAMERA
    opaque_output_subformats = ('OPQV-single', 'OPQV-dual', 'OPQV-strips')

    annotate_structs = (
        mmal.MMAL_PARAMETER_CAMERA_ANNOTATE_T,
        mmal.MMAL_PARAMETER_CAMERA_ANNOTATE_V2_T,
        mmal.MMAL_PARAMETER_CAMERA_ANNOTATE_V3_T,
        )

    def __init__(self):
        global FIX_RGB_BGR_ORDER
        super(MMALCamera, self).__init__()
        if PARAM_TYPES[mmal.MMAL_PARAMETER_ANNOTATE] is None:
            found = False
            # try largest struct to smallest as later firmwares still happily
            # accept earlier revision structures
            # XXX do old firmwares reject too-large structs?
            for struct in reversed(MMALCamera.annotate_structs):
                try:
                    PARAM_TYPES[mmal.MMAL_PARAMETER_ANNOTATE] = struct
                    self.control.params[mmal.MMAL_PARAMETER_ANNOTATE]
                except PiCameraMMALError:
                    pass
                else:
                    found = True
                    break
            if not found:
                PARAM_TYPES[mmal.MMAL_PARAMETER_ANNOTATE] = None
                raise PiCameraMMALError(
                        mmal.MMAL_EINVAL, "unknown camera annotation structure revision")
        if FIX_RGB_BGR_ORDER is None:
            try:
                self.outputs[2].supported_formats
            except PiCameraMMALError:
                # old firmware lists BGR24 before RGB24 in supported_formats
                for f in self.outputs[1].supported_formats:
                    if f == mmal.MMAL_ENCODING_BGR24:
                        FIX_RGB_BGR_ORDER = True
                        break
                    elif f == mmal.MMAL_ENCODING_RGB24:
                        FIX_RGB_BGR_ORDER = False
                        break
            else:
                # old firmware has a bug which prevents supported_formats
                # working on the still port
                FIX_RGB_BGR_ORDER = False

    def _get_annotate_rev(self):
        try:
            return MMALCamera.annotate_structs.index(PARAM_TYPES[mmal.MMAL_PARAMETER_ANNOTATE]) + 1
        except IndexError:
            raise PiCameraMMALError(
                    mmal.MMAL_EINVAL, "unknown camera annotation structure revision")
    def _set_annotate_rev(self, value):
        try:
            PARAM_TYPES[mmal.MMAL_PARAMETER_ANNOTATE] = MMALCamera.annotate_structs[value - 1]
        except IndexError:
            raise PiCameraMMALError(
                mmal.MMAL_EINVAL, "invalid camera annotation structure revision")
    annotate_rev = property(_get_annotate_rev, _set_annotate_rev, doc="""\
        The annotation capabilities of the firmware have evolved over time and
        several structures are available for querying and setting video
        annotations. By default the :class:`MMALCamera` class will pick the
        latest annotation structure supported by the current firmware but you
        can select older revisions with :attr:`annotate_rev` for other purposes
        (e.g. testing).
        """)


class MMALCameraInfo(MMALBaseComponent):
    """
    Represents the MMAL camera-info component. Query the
    ``MMAL_PARAMETER_CAMERA_INFO`` parameter on the control port to obtain
    information about the connected camera module.
    """
    __slots__ = ()

    component_type = mmal.MMAL_COMPONENT_DEFAULT_CAMERA_INFO

    info_structs = (
        mmal.MMAL_PARAMETER_CAMERA_INFO_T,
        mmal.MMAL_PARAMETER_CAMERA_INFO_V2_T,
        )

    def __init__(self):
        super(MMALCameraInfo, self).__init__()
        if PARAM_TYPES[mmal.MMAL_PARAMETER_CAMERA_INFO] is None:
            found = False
            # try smallest structure to largest as later firmwares reject
            # older structures
            for struct in MMALCameraInfo.info_structs:
                try:
                    PARAM_TYPES[mmal.MMAL_PARAMETER_CAMERA_INFO] = struct
                    self.control.params[mmal.MMAL_PARAMETER_CAMERA_INFO]
                except PiCameraMMALError:
                    pass
                else:
                    found = True
                    break
            if not found:
                PARAM_TYPES[mmal.MMAL_PARAMETER_CAMERA_INFO] = None
                raise PiCameraMMALError(
                        mmal.MMAL_EINVAL, "unknown camera info structure revision")

    def _get_info_rev(self):
        try:
            return MMALCameraInfo.info_structs.index(PARAM_TYPES[mmal.MMAL_PARAMETER_CAMERA_INFO]) + 1
        except IndexError:
            raise PiCameraMMALError(
                    mmal.MMAL_EINVAL, "unknown camera info structure revision")
    def _set_info_rev(self, value):
        try:
            PARAM_TYPES[mmal.MMAL_PARAMETER_CAMERA_INFO] = MMALCameraInfo.info_structs[value - 1]
        except IndexError:
            raise PiCameraMMALError(
                mmal.MMAL_EINVAL, "invalid camera info structure revision")
    info_rev = property(_get_info_rev, _set_info_rev, doc="""\
        The camera information capabilities of the firmware have evolved over
        time and several structures are available for querying camera
        information. When initialized, :class:`MMALCameraInfo` will attempt
        to discover which structure is in use by the extant firmware. This
        property can be used to discover the structure version and to modify
        the version in use for other purposes (e.g. testing).
        """)


class MMALComponent(MMALBaseComponent):
    """
    Represents an MMAL component that acts as a filter of some sort, with a
    single input that connects to an upstream source port. This is an asbtract
    base class.
    """
    __slots__ = ('_connection',)

    def __init__(self):
        super(MMALComponent, self).__init__()
        assert len(self.opaque_input_subformats) == 1
        self._connection = None

    def connect(self, source):
        """
        Connect this component's sole input port to the specified *source*
        :class:`MMALPort`. The type and configuration of the connection will
        be automatically selected, and the connection will be automatically
        enabled.
        """
        if self.connection is not None:
            self.disconnect()
        if isinstance(source, MMALPythonPort):
            self._connection = MMALPythonConnection(source, self.inputs[0])
        else:
            self._connection = MMALConnection(source, self.inputs[0])

    def disconnect(self):
        """
        Destroy the connection between this component's input port and the
        upstream component.
        """
        if self.connection is not None:
            self.connection.close()
            self._connection = None

    def close(self):
        self.disconnect()
        super(MMALComponent, self).close()

    def enable(self):
        super(MMALComponent, self).enable()
        if self.connection is not None:
            self.connection.enable()

    def disable(self):
        if self.connection is not None:
            self.connection.disable()
        super(MMALComponent, self).disable()

    @property
    def connection(self):
        """
        The :class:`MMALConnection` or :class:`MMALPythonConnection` object
        linking this component to the upstream component.
        """
        return self._connection


class MMALSplitter(MMALComponent):
    """
    Represents the MMAL splitter component. This component has 1 input port
    and 4 output ports which all generate duplicates of buffers passed to the
    input port.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_VIDEO_SPLITTER
    opaque_input_subformats = ('OPQV-single',)
    opaque_output_subformats = ('OPQV-single',) * 4


class MMALConverter(MMALComponent):
    """
    Represents the MMAL ISP component. This component has 1 input port and
    1 output port, and supports conversion of numerous formats into numerous
    other formats (e.g. OPAQUE to RGB, etc).
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_ISP
    opaque_input_subformats = ('OPQV-single',)
    opaque_output_subformats = (None,)


class MMALResizer(MMALComponent):
    """
    Represents the MMAL resizer component. This component has 1 input port and
    1 output port. The output port can (and usually should) have a different
    frame size to the input port.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_RESIZER
    opaque_input_subformats = (None,)
    opaque_output_subformats = (None,)


class MMALEncoder(MMALComponent):
    """
    Represents a generic MMAL encoder. This is an abstract base class.
    """
    __slots__ = ()


class MMALVideoEncoder(MMALEncoder):
    """
    Represents the MMAL video encoder component. This component has 1 input
    port and 1 output port. The output port is usually configured with
    ``MMAL_ENCODING_H264`` or ``MMAL_ENCODING_MJPEG``.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_VIDEO_ENCODER
    opaque_input_subformats = ('OPQV-dual',)
    opaque_output_subformats = (None,)


class MMALImageEncoder(MMALEncoder):
    """
    Represents the MMAL image encoder component. This component has 1 input
    port and 1 output port. The output port is typically configured with
    ``MMAL_ENCODING_JPEG`` but can also use ``MMAL_ENCODING_PNG``,
    ``MMAL_ENCODING_GIF``, etc.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_IMAGE_ENCODER
    opaque_input_subformats = ('OPQV-strips',)
    opaque_output_subformats = (None,)


class MMALDecoder(MMALComponent):
    """
    Represents a generic MMAL decoder. This is an abstract base class.
    """
    __slots__ = ()


class MMALVideoDecoder(MMALDecoder):
    """
    Represents the MMAL video decoder component. This component has 1 input
    port and ? output ports. The input port is usually configured with
    ``MMAL_ENCODING_H264`` or ``MMAL_ENCODING_MJPEG``.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_VIDEO_DECODER
    opaque_input_subformats = (None,)
    opaque_output_subformats = ('OPQV-single',)


class MMALImageDecoder(MMALDecoder):
    """
    Represents the MMAL iamge decoder component. This component has 1 input
    port and 1 output port. The input port is usually configured with
    ``MMAL_ENCODING_JPEG``.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_IMAGE_DECODER
    opaque_input_subformats = (None,)
    opaque_output_subformats = ('OPQV-single',)


class MMALRenderer(MMALComponent):
    """
    Represents the MMAL renderer component. This component has 1 input port and
    0 output ports. It is used to implement the camera preview and overlays.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_VIDEO_RENDERER
    opaque_input_subformats = ('OPQV-single',)


class MMALNullSink(MMALComponent):
    """
    Represents the MMAL null-sink component. This component has 1 input port
    and 0 output ports. It is used to keep the preview port "alive" (and thus
    calculating white-balance and exposure) when the camera preview is not
    required.
    """
    __slots__ = ()
    component_type = mmal.MMAL_COMPONENT_DEFAULT_NULL_SINK
    opaque_input_subformats = ('OPQV-single',)


class MMALPythonPort(MMALObject):
    """
    Implements ports for Python-based MMAL components.
    """
    __slots__ = (
        '_buffer_count',
        '_buffer_size',
        '_connection',
        '_enabled',
        '_owner',
        '_pool',
        '_type',
        '_index',
        '_format',
        '_callback',
        '_thread',
        '_queue',
        )

    _FORMAT_BPP = {
        'I420': 1.5,
        'RGB3': 3,
        'RGBA': 4,
        'BGR3': 3,
        'BGRA': 4,
        }

    def __init__(self, owner, port_type, index):
        self._buffer_count = 2
        self._buffer_size = 0
        self._connection = None
        self._enabled = False
        self._owner = owner
        self._pool = None
        self._callback = None
        self._thread = None
        self._queue = Queue(maxsize=2) # see send_buffer for maxsize reason
        self._type = port_type
        self._index = index
        self._format = ct.pointer(mmal.MMAL_ES_FORMAT_T(
            type=mmal.MMAL_ES_TYPE_VIDEO,
            encoding=mmal.MMAL_ENCODING_I420,
            es=ct.pointer(mmal.MMAL_ES_SPECIFIC_FORMAT_T())))

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self.disable()
        self._queue = None
        self._format = None

    def _get_bitrate(self):
        return self._format[0].bitrate
    def _set_bitrate(self, value):
        self._format[0].bitrate = value
    bitrate = property(_get_bitrate, _set_bitrate, doc="""\
        Retrieves or sets the bitrate limit for the port's format.
        """)

    def _get_format(self):
        return self._format[0].encoding
    def _set_format(self, value):
        self._format[0].encoding = value
    format = property(_get_format, _set_format, doc="""\
        Retrieves or sets the encoding format of the port. Setting this
        attribute implicitly sets the encoding variant to a sensible value
        (I420 in the case of OPAQUE).
        """)

    def _get_framesize(self):
        return PiResolution(
            self._format[0].es[0].video.crop.width,
            self._format[0].es[0].video.crop.height,
            )
    def _set_framesize(self, value):
        value = to_resolution(value)
        video = self._format[0].es[0].video
        video.width = bcm_host.VCOS_ALIGN_UP(value.width, 32)
        video.height = bcm_host.VCOS_ALIGN_UP(value.height, 16)
        video.crop.width = value.width
        video.crop.height = value.height
    framesize = property(_get_framesize, _set_framesize, doc="""\
        Retrieves or sets the size of the source's video frames as a (width,
        height) tuple. This attribute implicitly handles scaling the given
        size up to the block size of the camera (32x16).
        """)

    def _get_framerate(self):
        video = self._format[0].es[0].video
        try:
            return Fraction(
                video.frame_rate.num,
                video.frame_rate.den)
        except ZeroDivisionError:
            return Fraction(0, 1)
    def _set_framerate(self, value):
        value = to_fraction(value)
        video = self._format[0].es[0].video
        video.frame_rate.num = value.numerator
        video.frame_rate.den = value.denominator
    framerate = property(_get_framerate, _set_framerate, doc="""\
        Retrieves or sets the framerate of the port's video frames in fps.
        """)

    @property
    def pool(self):
        """
        Returns the :class:`MMALPool` associated with the buffer, if any.
        """
        return self._pool

    @property
    def opaque_subformat(self):
        return None

    def _get_buffer_count(self):
        return self._buffer_count
    def _set_buffer_count(self, value):
        if value < 1:
            raise PiCameraMMALError(mmal.MMAL_EINVAL, 'buffer count <1')
        self._buffer_count = int(value)
    buffer_count = property(_get_buffer_count, _set_buffer_count, doc="""\
        The number of buffers allocated (or to be allocated) to the port. The
        default is 2 but more may be required in the case of long pipelines
        with replicated buffers.
        """)

    def _get_buffer_size(self):
        return self._buffer_size
    def _set_buffer_size(self, value):
        if value < 0:
            raise PiCameraMMALError(mmal.MMAL_EINVAL, 'buffer size <0')
        self._buffer_size = value
    buffer_size = property(_get_buffer_size, _set_buffer_size, doc="""\
        The size of buffers allocated (or to be allocated) to the port. The
        size of buffers defaults to a value dictated by the port's format.
        """)

    def copy_from(self, source):
        """
        Copies the port's :attr:`format` from the *source*
        :class:`MMALControlPort`.
        """
        if isinstance(source, MMALPythonPort):
            mmal.mmal_format_copy(self._format, source._format)
        else:
            mmal.mmal_format_copy(self._format, source._port[0].format)

    def commit(self):
        """
        Commits the port's configuration and automatically updates the number
        and size of associated buffers. This is typically called after
        adjusting the port's format and/or associated settings (like width and
        height for video ports).
        """
        self._buffer_count = 2
        video = self._format[0].es[0].video
        try:
            self._buffer_size = int(
                MMALPythonPort._FORMAT_BPP[str(self.format)]
                * video.width
                * video.height)
        except KeyError:
            # If it's an unknown / encoded format just leave the buffer size
            # alone and hope the owning component knows what to set
            pass
        self._owner._commit_port(self)

    @property
    def enabled(self):
        """
        Returns a :class:`bool` indicating whether the port is currently
        enabled. Unlike other classes, this is a read-only property. Use
        :meth:`enable` and :meth:`disable` to modify the value.
        """
        return self._enabled

    def enable(self, callback=None):
        """
        Enable the port with the specified callback function (this must be
        ``None`` for connected ports, and a callable for disconnected ports).

        The callback function must accept two parameters which will be this
        :class:`MMALControlPort` (or descendent) and an :class:`MMALBuffer`
        instance. Any return value will be ignored.
        """
        if self.type == mmal.MMAL_PORT_TYPE_OUTPUT:
            if self._connection is not None:
                if callback is not None:
                    raise PiCameraMMALError(
                        mmal.MMAL_EINVAL,
                        'connected python output ports must be enabled '
                        'without callback')
            else:
                if callback is None:
                    raise PiCameraMMALError(
                        mmal.MMAL_EINVAL,
                        'unconnected python output ports must be enabled '
                        'with callback')
                self._pool = MMALPythonPortPool(self)
        else:
            if callback is None:
                raise PiCameraMMALError(
                    mmal.MMAL_EINVAL,
                    'python input ports must be enabled with callback')
            # The port is an input port; set up a background thread to handle
            # incoming buffers via the specified callback
            self._pool = MMALPythonPortPool(self)
            self._thread = Thread(target=self._callback_run)
            self._thread.daemon = True
        self._callback = callback
        self._enabled = True
        if self._thread is not None:
            self._thread.start()

    def disable(self):
        """
        Disable the port.
        """
        self._enabled = False
        if self._thread is not None:
            self._thread.join()
            while not self._queue.empty():
                self._queue.get()
            self._thread = None
        if self._pool is not None:
            self._pool.close()
            self._pool = None
        self._callback = None

    def _format_changed(self, buf):
        with buf as data:
            event = mmal.mmal_event_format_changed_get(buf._buf)
            if self._connection:
                # Handle format change on the source output port, if any. We don't
                # check the output port capabilities because it was the port that
                # emitted the event change in the first case so it'd be odd if it
                # didn't support them (or the format requested)!
                output = self._connection._source
                output.disable()
                if isinstance(output, MMALPythonPort):
                    mmal.mmal_format_copy(output._format, event[0].format)
                else:
                    mmal.mmal_format_copy(output._port[0].format, event[0].format)
                output.commit()
                output.buffer_count = (
                    event[0].buffer_num_recommended
                    if event[0].buffer_num_recommended > 0 else
                    event[0].buffer_num_min)
                output.buffer_size = (
                    event[0].buffer_size_recommended
                    if event[0].buffer_size_recommended > 0 else
                    event[0].buffer_size_min)
                if isinstance(output, MMALPythonPort):
                    output.enable()
                else:
                    output.enable(self._connection._transfer)
            # Now deal with the format change on this input port (this is only
            # called from _callback_run so we must be an input port)
            try:
                if not (self.capabilities & mmal.MMAL_PORT_CAPABILITY_SUPPORTS_EVENT_FORMAT_CHANGE):
                    raise PiCameraMMALError(
                        mmal.MMAL_EINVAL,
                        'port %s does not support event change' % self.name)
                mmal.mmal_format_copy(self._format, event[0].format)
                self._owner._commit_port(self)
                self._pool.resize(
                    event[0].buffer_num_recommended
                    if event[0].buffer_num_recommended > 0 else
                    event[0].buffer_num_min,
                    event[0].buffer_size_recommended
                    if event[0].buffer_size_recommended > 0 else
                    event[0].buffer_size_min)
                self._buffer_count = len(self._pool)
                self._buffer_size = self._pool[0].size
            except:
                # If this port can't handle the format change, or if anything goes
                # wrong (like the owning component doesn't like the new format)
                # stop the pipeline (from here at least)
                if self._connection:
                    self._connection.disable()
                raise

    def _callback_run(self):
        while self._enabled:
            try:
                buf = self._queue.get(timeout=0.1)
            except Empty:
                pass
            else:
                try:
                    if buf.command == mmal.MMAL_EVENT_FORMAT_CHANGED:
                        self._format_changed(buf)
                        # Chain the format-change onward so everything
                        # downstream sees it. NOTE: the callback isn't given
                        # the format-change because there's no image data in it
                        for output in self._owner.outputs:
                            out_buf = output.get_buffer()
                            out_buf.copy_from(buf)
                            output.send_buffer(out_buf)
                    elif self._owner.enabled:
                        # XXX Do something with the return value?
                        self._callback(self, buf)
                finally:
                    buf.release()

    def get_buffer(self, block=True, timeout=None):
        """
        Returns a :class:`MMALBuffer` from the associated :attr:`pool`. *block*
        and *timeout* act as they do in the corresponding
        :meth:`MMALPool.get_buffer`.
        """
        if not self._enabled:
            raise PiCameraMMALError(
                mmal.MMAL_EINVAL, 'cannot get buffers from disabled port')
        if self._callback is not None:
            assert self._pool
            return self._pool.get_buffer(block, timeout)
        else:
            assert self.type == mmal.MMAL_PORT_TYPE_OUTPUT
            return self._connection._target.get_buffer(block, timeout)

    def send_buffer(self, buf):
        """
        Send :class:`MMALBuffer` *buf* to the port.
        """
        if not self._enabled:
            raise PiCameraMMALError(
                mmal.MMAL_EINVAL, 'cannot send buffers via disabled port')
        if self._thread is not None:
            # Asynchronous input port case; queue the buffer for processing.
            # The maximum queue size ensures that this call blocks if the
            # owning component isn't keeping up. This means upstream components
            # drop frames if required to keep the pipeline running
            self._queue.put(buf)
        elif self._callback is not None:
            # Disconnected output port case; run the port's callback with the
            # buffer
            # XXX Do something with the return value?
            self._callback(self, buf)
        else:
            # Connected output port case; forward the buffer to the connected
            # component's input port
            assert self.type == mmal.MMAL_PORT_TYPE_OUTPUT
            # XXX If it's a format-change event?
            self._connection._target.send_buffer(buf)

    @property
    def name(self):
        return '%s:%s:%d' % (self._owner.name, {
            mmal.MMAL_PORT_TYPE_OUTPUT:  'out',
            mmal.MMAL_PORT_TYPE_INPUT:   'in',
            mmal.MMAL_PORT_TYPE_CONTROL: 'control',
            mmal.MMAL_PORT_TYPE_CLOCK:   'clock',
            }[self.type], self._index)

    @property
    def type(self):
        """
        The type of the port. One of:

        * MMAL_PORT_TYPE_OUTPUT
        * MMAL_PORT_TYPE_INPUT
        * MMAL_PORT_TYPE_CONTROL
        * MMAL_PORT_TYPE_CLOCK
        """
        return self._type

    @property
    def capabilities(self):
        """
        The capabilities of the port. A bitfield of the following:

        * MMAL_PORT_CAPABILITY_PASSTHROUGH
        * MMAL_PORT_CAPABILITY_ALLOCATION
        * MMAL_PORT_CAPABILITY_SUPPORTS_EVENT_FORMAT_CHANGE
        """
        return mmal.MMAL_PORT_CAPABILITY_SUPPORTS_EVENT_FORMAT_CHANGE

    @property
    def index(self):
        """
        Returns an integer indicating the port's position within its owning
        list (inputs, outputs, etc.)
        """
        return self._index

    def __repr__(self):
        return '<MMALPythonPort "%s": format=%r buffers=%dx%d frames=%s@%sfps>' % (
            self.name, self.format, self.buffer_count, self.buffer_size, self.framesize, self.framerate)


class MMALPythonPortPool(MMALPool):
    """
    Creates a pool of buffer headers for an :class:`MMALPythonPort`. This is
    only used when a fake port is used without a corresponding
    :class:`MMALPythonConnection`.
    """
    __slots__ = ('_port',)

    def __init__(self, port):
        super(MMALPythonPortPool, self).__init__(
            mmal.mmal_pool_create(port.buffer_count, port.buffer_size))
        self._port = port

    @property
    def port(self):
        return self._port

    def send_buffer(self, block=True, timeout=None):
        """
        Get a buffer from the pool and send it to the port the pool is
        associated with. *block* and *timeout* operate as they do in
        :meth:`MMALPool.get_buffer`.
        """
        super(MMALPythonPortPool, self).send_buffer(self._port, block, timeout)

    def send_all_buffers(self, block=True, timeout=None):
        """
        Send all buffers from the pool to the port the pool is associated with.
        *block* and *timeout* operate as they do in
        :meth:`MMALPool.get_buffer`.
        """
        super(MMALPythonPortPool, self).send_all_buffers(self._port, block, timeout)


class MMALPythonBaseComponent(MMALObject):
    """
    Base class for Python-implemented MMAL components. This class provides the
    :meth:`_commit_port` method used by descendents to control their ports'
    behaviour, and the :attr:`enabled` property. However, it is unlikely that
    users will want to sub-class this directly. See
    :class:`MMALPythonComponent` for a more useful starting point.
    """
    __slots__ = ('_inputs', '_outputs', '_enabled',)

    def __init__(self):
        super(MMALPythonBaseComponent, self).__init__()
        self._enabled = False
        self._inputs = ()
        self._outputs = ()

    def close(self):
        """
        Close the component and release all its resources. After this is
        called, most methods will raise exceptions if called.
        """
        self.disable()

    @property
    def enabled(self):
        """
        Returns ``True`` if the component is currently enabled. Use
        :meth:`enable` and :meth:`disable` to control the component's state.
        """
        return self._enabled

    def enable(self):
        """
        Enable the component. When a component is enabled it will process data
        sent to its input port(s), sending the results to buffers on its output
        port(s). Components may be implicitly enabled by connections.
        """
        self._enabled = True

    def disable(self):
        """
        Disables the component.
        """
        self._enabled = False

    @property
    def control(self):
        """
        The :class:`MMALControlPort` control port of the component which can be
        used to configure most aspects of the component's behaviour.
        """
        return None

    @property
    def inputs(self):
        """
        A sequence of :class:`MMALPort` objects representing the inputs
        of the component.
        """
        return self._inputs

    @property
    def outputs(self):
        """
        A sequence of :class:`MMALPort` objects representing the outputs
        of the component.
        """
        return self._outputs

    def _commit_port(self, port):
        """
        Called by ports when their format is committed. Descendents may
        override this to reconfigure output ports when input ports are
        committed, or to raise errors if the new port configuration is
        unacceptable.

        .. warning::

            This method must *not* reconfigure input ports when called; however
            it can reconfigure *output* ports when input ports are committed.
        """
        pass

    def __repr__(self):
        if self._outputs:
            return '<%s "%s": %d inputs %d outputs>' % (
                self.__class__.__name__, self.name,
                len(self.inputs), len(self.outputs))
        else:
            return '<%s closed>' % self.__class__.__name__


class MMALPythonSource(MMALPythonBaseComponent):
    """
    Provides a source for other :class:`MMALComponent` instances. The
    specified *input* is read in chunks the size of the configured output
    buffer(s) until the input is exhausted. The :meth:`wait` method can be
    used to block until this occurs. If the output buffer is configured to
    use a full-frame unencoded format (like I420 or RGB), frame-end flags will
    be automatically generated by the source. When the input is exhausted an
    empty buffer with the End Of Stream (EOS) flag will be sent.

    The component provides all picamera's usual IO-handling characteristics; if
    *input* is a string, a file with that name will be opened as the input and
    closed implicitly when the component is closed. Otherwise, the input will
    not be closed implicitly (the component did not open it, so the assumption
    is that closing *input* is the caller's responsibility). If *input* is an
    object with a ``read`` method it is assumed to be a file-like object and is
    used as is. Otherwise, *input* is assumed to be a readable object
    supporting the buffer protocol (which is wrapped in a :class:`BufferIO`
    stream).
    """
    __slots__ = ('_stream', '_opened', '_thread')

    def __init__(self, input):
        super(MMALPythonSource, self).__init__()
        self._inputs = ()
        self._outputs = (MMALPythonPort(self, mmal.MMAL_PORT_TYPE_OUTPUT, 0),)
        self._stream, self._opened = open_stream(input, output=False)
        self._thread = None

    def close(self):
        super(MMALPythonSource, self).close()
        if self._outputs:
            self._outputs[0].close()
            self._outputs = ()
        if self._stream:
            close_stream(self._stream, self._opened)
            self._stream = None

    def enable(self):
        super(MMALPythonSource, self).enable()
        self._thread = Thread(target=self._send_run)
        self._thread.daemon = True
        self._thread.start()

    def disable(self):
        super(MMALPythonSource, self).disable()
        if self._thread:
            self._thread.join()
            self._thread = None

    def wait(self, timeout=None):
        """
        Wait for the source to send all bytes from the specified input. If
        *timeout* is specified, it is the number of seconds to wait for
        completion. The method returns ``True`` if the source completed within
        the specified timeout and ``False`` otherwise.
        """
        if not self.enabled:
            raise PiCameraMMALError(
                mmal.MMAL_EINVAL, 'cannot wait on disabled component')
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _send_run(self):
        # Calculate the size of a frame if possible (i.e. when the output
        # format is an unencoded full frame format). If it's an unknown /
        # encoded format, we've no idea what the framesize is (this would
        # presumably require decoding the stream) so leave framesize as None.
        video = self._outputs[0]._format[0].es[0].video
        try:
            framesize = (
                MMALPythonPort._FORMAT_BPP[str(self._outputs[0].format)]
                * video.width
                * video.height)
        except KeyError:
            framesize = None
        frameleft = framesize
        while self.enabled:
            buf = self._outputs[0].get_buffer(timeout=0.1)
            if buf:
                try:
                    if frameleft is None:
                        send = buf.size
                    else:
                        send = min(frameleft, buf.size)
                    with buf as data:
                        if send == buf.size:
                            try:
                                # readinto() is by far the fastest method of
                                # getting data into the buffer
                                buf.length = self._stream.readinto(data)
                            except AttributeError:
                                # if there's no readinto() method, fallback on
                                # read() and the data setter (memmove)
                                buf.data = self._stream.read(buf.size)
                        else:
                            buf.data = self._stream.read(send)
                    if frameleft is not None:
                        frameleft -= buf.length
                        if not frameleft:
                            buf.flags |= mmal.MMAL_BUFFER_HEADER_FLAG_FRAME_END
                            frameleft = framesize
                    if not buf.length:
                        buf.flags |= mmal.MMAL_BUFFER_HEADER_FLAG_EOS
                        break
                finally:
                    self._outputs[0].send_buffer(buf)

    @property
    def name(self):
        return 'py.source'


class MMALPythonComponent(MMALPythonBaseComponent):
    """
    Provides a Python-based MMAL component with a *name*, a single input and
    the specified number of *outputs* (default 1). The :meth:`connect` and
    :meth:`disconnect` methods can be used to establish or break a connection
    from the input port to an upstream component.

    Override the :meth:`_callback` method to respond to buffers sent to the
    input port, and the :meth:`_commit_port` method to control what formats
    and framesizes the component works with.
    """
    __slots__ = ('_name',)

    def __init__(self, name='py.component', outputs=1):
        super(MMALPythonComponent, self).__init__()
        self._name = name
        self._inputs = (MMALPythonPort(self, mmal.MMAL_PORT_TYPE_INPUT, 0),)
        self._outputs = tuple(
            MMALPythonPort(self, mmal.MMAL_PORT_TYPE_OUTPUT, n)
            for n in range(outputs)
            )

    def close(self):
        super(MMALPythonComponent, self).close()
        if self._inputs:
            self._inputs[0].close()
            self._inputs = ()
        if self._outputs:
            for output in self._outputs:
                output.disable()
            self._outputs = ()

    def connect(self, source):
        """
        Connect this component's sole input port to the specified *source*
        :class:`MMALPort`. The type and configuration of the connection will
        be automatically selected, and the connection will be automatically
        enabled.
        """
        if self.connection is not None:
            self.disconnect()
        self._inputs[0]._connection = MMALPythonConnection(
            source, self.inputs[0], callback=self._callback)

    def disconnect(self):
        """
        Destroy the connection between this component's input port and the
        upstream component.
        """
        if self.connection is not None:
            self.connection.close()
            self._inputs[0]._connection = None

    @property
    def connection(self):
        """
        The :class:`MMALConnection` or :class:`MMALPythonConnection` object
        linking this component to the upstream component.
        """
        return self._inputs[0]._connection

    @property
    def name(self):
        return self._name

    def _commit_port(self, port):
        """
        Overridden to to copy the input port's configuration to the output
        port(s), and to ensure that the output port(s)' format(s) match
        the input port's format.
        """
        super(MMALPythonComponent, self)._commit_port(port)
        if port.type == mmal.MMAL_PORT_TYPE_INPUT:
            for output in self.outputs:
                output.copy_from(port)
        elif port.type == mmal.MMAL_PORT_TYPE_OUTPUT:
            if port.format.value != self.inputs[0].format.value:
                raise PiCameraMMALError(mmal.MMAL_EINVAL, 'output format mismatch')

    def _accept_formats(self, port, valid):
        """
        A utility method intended for use within :meth:`_commit_port`. If the
        *port* format is not one of the values listed in the *valid* sequence,
        the appropriate :exc:`~picamera.PiCameraMMALError` is raised.
        """
        try:
            iter(valid)
        except TypeError:
            valid = (valid,)
        if port.format.value not in valid:
            raise PiCameraMMALError(
                mmal.MMAL_EINVAL, 'invalid format for port %r' % port)

    def _callback(self, port, buf):
        """
        Stub for descendents to override. This will be called with each buffer
        sent to the input port.

        If the component has output ports, the method is expected to fetch a
        buffer from the output port(s), write data into them, and send them
        back to their respective ports.

        Return values are as for normal port callbacks (``True`` when no more
        buffers are expected, ``False`` otherwise).
        """
        return False


class MMALPythonTarget(MMALPythonComponent):
    """
    Provides a simple component that writes all received buffers to the
    specified *output* until a frame with the *done* flag is seen (defaults to
    MMAL_BUFFER_HEADER_FLAG_EOS indicating End Of Stream).

    The component provides all picamera's usual IO-handling characteristics; if
    *output* is a string, a file with that name will be opened as the output
    and closed implicitly when the component is closed. Otherwise, the output
    will not be closed implicitly (the component did not open it, so the
    assumption is that closing *output* is the caller's responsibility). If
    *output* is an object with a ``write`` method it is assumed to be a
    file-like object and is used as is. Otherwise, *output* is assumed to be a
    writeable object supporting the buffer protocol (which is wrapped in a
    :class:`BufferIO` stream).
    """
    __slots__ = ('_opened', '_stream', '_done', '_event')

    def __init__(self, output, done=mmal.MMAL_BUFFER_HEADER_FLAG_EOS):
        super(MMALPythonTarget, self).__init__(name='py.target', outputs=0)
        self._inputs = (MMALPythonPort(self, mmal.MMAL_PORT_TYPE_INPUT, 0),)
        self._outputs = ()
        self._stream, self._opened = open_stream(output)
        self._done = done
        self._event = Event()

    def close(self):
        super(MMALPythonTarget, self).close()
        close_stream(self._stream, self._opened)

    def enable(self):
        self._event.clear()
        super(MMALPythonTarget, self).enable()

    def wait(self, timeout=None):
        """
        Wait for the output to be "complete" as defined by the constructor's
        *done* parameter. If *timeout* is specified it is the number of seconds
        to wait for completion. The method returns ``True`` if the target
        completed within the specified timeout and ``False`` otherwise.
        """
        return self._event.wait(timeout)

    def _callback(self, port, buf):
        self._stream.write(buf.data)
        if buf.flags & self._done:
            self._event.set()
            return True
        return False


class MMALPythonConnection(MMALObject):
    """
    Represents a connection between an :class:`MMALPythonBaseComponent` and a
    :class:`MMALBaseComponent` or another :class:`MMALPythonBaseComponent`.
    """
    __slots__ = ('_enabled', '_callback', '_source', '_target')

    def __init__(self, source, target, callback=None):
        if not (
                isinstance(source, MMALPythonPort) or
                isinstance(target, MMALPythonPort)
                ):
            raise PiCameraValueError('use a real MMAL connection')
        if not isinstance(source, (MMALPort, MMALPythonPort)):
            raise PiCameraValueError('source is not a port')
        if not isinstance(target, (MMALPort, MMALPythonPort)):
            raise PiCameraValueError('target is not a port')
        self._enabled = False
        if callback is None:
            callback = lambda port, buf: True
        self._callback = callback
        self._source = source
        self._target = target
        self._negotiate_format()
        if isinstance(self._source, MMALPythonPort):
            self._source._connection = self
        if isinstance(self._target, MMALPythonPort):
            self._target._connection = self
        self.enable()

    def _negotiate_format(self):
        # Attempt to find a port format that both source and target will
        # accept. The following algorithm attempts the existing formats first
        # to avoid switching format unless absolutely necessary, on the
        # possibility that the caller may have configured things with "known
        # good" settings that they wish to keep
        formats = [
            # list of formats to try in descending order of preference
            mmal.MMAL_ENCODING_BGRA,
            mmal.MMAL_ENCODING_RGBA,
            mmal.MMAL_ENCODING_BGR24,
            mmal.MMAL_ENCODING_RGB24,
            mmal.MMAL_ENCODING_I420,
            ]
        try:
            # remove the source port's initial format from the list to be tried
            # as it'll be tried anyway by the first iteration of the loop below
            formats.remove(self._source.format.value)
        except ValueError:
            pass
        while True:
            try:
                self._source.commit()
                self._target.copy_from(self._source)
                self._target.commit()
            except PiCameraMMALError:
                try:
                    self._source.format = formats.pop()
                except IndexError:
                    raise PiCameraMMALError(mmal.MMAL_EINVAL, 'failed to negotiate format')
            else:
                self._source.buffer_count = self._target.buffer_count = max(
                    self._source.buffer_count, self._target.buffer_count)
                self._source.buffer_size = self._target.buffer_size = max(
                    self._source.buffer_size, self._target.buffer_size)
                break

    def close(self):
        self.disable()
        if isinstance(self._source, MMALPythonPort):
            self._source._connection = None
        if isinstance(self._target, MMALPythonPort):
            self._target._connection = None

    @property
    def enabled(self):
        """
        Returns ``True`` if the connection is enabled. Use :meth:`enable`
        and :meth:`disable` to control the state of the connection.
        """
        return self._enabled

    def enable(self):
        """
        Enable the connection. When a connection is enabled, data is
        continually transferred from the output port of the source to the input
        port of the target component.
        """
        if not self._enabled:
            self._enabled = True
            self._target.enable(self._callback)
            if isinstance(self._source, MMALPythonPort):
                # Connected python output ports are nothing more than thin
                # proxies for the target input port; no callback required
                self._source.enable()
            else:
                # Connected MMAL output ports are made to transfer their
                # data to the Python input port
                self._source.enable(self._transfer)

    def disable(self):
        """
        Disables the connection.
        """
        self._source.disable()
        self._target.disable()
        self._enabled = False

    def _transfer(self, port, buf):
        while self._enabled:
            try:
                dest = self._target.get_buffer(timeout=0.01)
            except PiCameraMMALError as e:
                if e.status == mmal.MMAL_EINVAL:
                    # The port was disabled; tell the source we're done
                    return True
                else:
                    raise
            else:
                if dest:
                    dest.copy_from(buf)
                    self._target.send_buffer(dest)
                    return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    @property
    def name(self):
        return '%s/%s' % (self._source.name, self._target.name)

    def __repr__(self):
        return '<MMALPythonConnection "%s">' % self.name


