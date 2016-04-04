# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Converts cubic bezier curves to quadratic splines.

Conversion is performed such that the quadratic splines keep the same end-curve
tangents as the original cubics. The approach is iterative, increasing the
number of segments for a spline until the error gets below a bound.

Respective curves from multiple fonts will be converted at once to ensure that
the resulting splines are interpolation-compatible.
"""


from __future__ import print_function, division, absolute_import

from fontTools.pens.basePen import AbstractPen
from cu2qu import curve_to_quadratic, curves_to_quadratic

__all__ = ['fonts_to_quadratic', 'font_to_quadratic']

DEFAULT_MAX_ERR = 0.0025


_zip = zip
def zip(*args):
    """Ensure each argument to zip has the same length."""

    if len(set(len(a) for a in args)) != 1:
        msg = 'Args to zip in cu2qu should have equal lengths: '
        raise ValueError(msg + ' '.join(str(a) for a in args))
    return _zip(*args)


class GetSegmentsPen(AbstractPen):
    """Pen to collect segments into lists of points for conversion."""

    def __init__(self):
        self._last_pt = None
        self.segments = []

    def _add_segment(self, tag, *args):
        self.segments.append((tag, args))

    def moveTo(self, pt):
        self._add_segment('move', pt)
        self._last_pt = pt

    def lineTo(self, pt):
        self._add_segment('line', pt)
        self._last_pt = pt

    def curveTo(self, *points):
        self._add_segment('curve', self._last_pt, *points)
        self._last_pt = points[-1]

    def closePath(self):
        self._add_segment('close')

    def addComponent(self, glyphName, transformation):
        self._add_segment('component', glyphName, transformation)


def _get_segments(glyph):
    """Get a glyph's segments as extracted by GetSegmentsPen."""

    pen = GetSegmentsPen()
    glyph.draw(pen)
    return pen.segments


def _set_segments(glyph, segments):
    """Draw segments as extracted by GetSegmentsPen back to a glyph."""

    glyph.clearContours()
    pen = glyph.getPen()
    for tag, args in segments:
        if tag == 'move':
            pen.moveTo(*args)
        elif tag == 'line':
            pen.lineTo(*args)
        elif tag == 'qcurve':
            pen.qCurveTo(*args[1:])
        elif tag == 'close':
            pen.closePath()
        elif tag == 'component':
            pen.addComponent(*args)
        else:
            raise AssertionError('Unhandled segment type %s' % tag)


def _segments_to_quadratic(segments, max_err, stats):
    """Return quadratic approximations of cubic segments."""

    assert all(s[0] == 'curve' for s in segments), 'Non-cubic given to convert'

    new_points, _ = curves_to_quadratic([s[1] for s in segments], max_err)
    n = len(new_points[0])
    assert all(len(s) == n for s in new_points[1:]), 'Converted incompatibly'

    n = str(n)
    if stats is not None:
        stats[n] = stats.get(n, 0) + 1

    return [('qcurve', p) for p in new_points]


def _fonts_to_quadratic(fonts, max_err, stats):
    """Do the actual conversion of fonts, after arguments have been set up."""

    for glyphs in zip(*fonts):
        name = glyphs[0].name
        assert all(g.name == name for g in glyphs), 'Incompatible fonts'

        segments_by_location = zip(*[_get_segments(g) for g in glyphs])
        if not any(segments_by_location):
            continue

        new_segments_by_location = []
        for segments in segments_by_location:
            tag = segments[0][0]
            assert all(s[0] == tag for s in segments[1:]), (
                'Incompatible glyphs "%s"' % name)
            if tag == 'curve':
                segments = _segments_to_quadratic(segments, max_err, stats)
            new_segments_by_location.append(segments)

        new_segments_by_glyph = zip(*new_segments_by_location)
        for glyph, new_segments in zip(glyphs, new_segments_by_glyph):
            _set_segments(glyph, new_segments)


def fonts_to_quadratic(fonts, max_err_em=None, max_err=None,
        stats=None, dump_stats=False):
    """Convert the curves of a collection of fonts to quadratic.

    All curves will be converted to quadratic at once, ensuring interpolation
    compatibility. If this is not required, calling fonts_to_quadratic with one
    font at a time may yield slightly more optimized results.
    """

    if stats is None:
        stats = {}

    if max_err_em and max_err:
        raise TypeError('Only one of max_err and max_err_em can be specified.')
    if not (max_err_em or max_err):
        max_err_em = DEFAULT_MAX_ERR

    if isinstance(max_err, (list, tuple)):
        max_errors = max_err
    elif isinstance(max_err_em, (list, tuple)):
        max_errors = max_err_em
    elif max_err:
        max_errors = [max_err] * len(fonts)
    else:
        max_errors = [f.info.unitsPerEm * max_err_em for f in fonts]

    num_fonts = len(fonts)
    assert len(max_errors) == num_fonts

    _fonts_to_quadratic(fonts, max_errors, stats)

    if dump_stats:
        spline_lengths = stats.keys()
        spline_lengths.sort()
        print('New spline lengths:\n%s\n' % (
            '\n'.join('%s: %d' % (l, stats[l]) for l in spline_lengths)))
    return stats


def font_to_quadratic(font, **kwargs):
    """Convenience wrapper around fonts_to_quadratic, for just one font."""

    fonts_to_quadratic([font], **kwargs)
