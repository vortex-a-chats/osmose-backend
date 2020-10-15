#!/usr/bin/env python
#-*- coding: utf-8 -*-

###########################################################################
##                                                                       ##
## Copyrights Frédéric Rodrigo 2012-2015                                 ##
##                                                                       ##
## This program is free software: you can redistribute it and/or modify  ##
## it under the terms of the GNU General Public License as published by  ##
## the Free Software Foundation, either version 3 of the License, or     ##
## (at your option) any later version.                                   ##
##                                                                       ##
## This program is distributed in the hope that it will be useful,       ##
## but WITHOUT ANY WARRANTY; without even the implied warranty of        ##
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         ##
## GNU General Public License for more details.                          ##
##                                                                       ##
## You should have received a copy of the GNU General Public License     ##
## along with this program.  If not, see <http://www.gnu.org/licenses/>. ##
##                                                                       ##
###########################################################################

from modules.OsmoseTranslation import T_
from .Analyser_Osmosis import Analyser_Osmosis

sql10 = """
CREATE OR REPLACE FUNCTION discard(x1 float, y1 float, x2 float, y2 float, x3 float, y3 float) RETURNS float AS $$
DECLARE d12 float; -- distance between 1 and 2
DECLARE d23 float; -- distance between 2 and 3
DECLARE d31 float; -- distance between 3 and 1
DECLARE ag float; -- angle
DECLARE rc float; -- radius
DECLARE cosB float;
DECLARE f float; -- discard
BEGIN
    d12 = dsqrt(dpow(x2 - x1,2) + dpow(y2 - y1,2));
    d23 = dsqrt(dpow(x3 - x2,2) + dpow(y3 - y2,2));
    d31 = dsqrt(dpow(x1 - x3,2) + dpow(y1 - y3,2));
    cosB = dpow(d31, 2) - dpow(d12, 2) - dpow(d23, 2);
    cosB = cosB / (2 * d12 * d23);
    ag = 180 - (acos(cosB) * 180 / pi());
    rc = (d23/2)/(cos((ag-90)*pi()/180));
    f = -(dsqrt(dpow(rc,2)-dpow((d23/2),2))-rc);
    RETURN f;
END;
$$ LANGUAGE plpgsql
   IMMUTABLE;
"""

sql11 = """
CREATE OR REPLACE FUNCTION discard3points(p1 geometry, p2 geometry, p3 geometry) RETURNS integer AS $$
BEGIN
    RETURN (discard(ST_X(p1), ST_Y(p1), ST_X(p2), ST_Y(p2), ST_X(p3), ST_Y(p3))/2)::int;
EXCEPTION
WHEN division_by_zero THEN
    --RAISE INFO 'division_by_zero';
    RETURN 0;
WHEN numeric_value_out_of_range THEN
    --RAISE INFO 'numeric_value_out_of_range';
    RETURN 0;
END;
$$ LANGUAGE plpgsql
   IMMUTABLE;
"""

sql12 = """
SELECT
    foo.id,
    ST_AsText(ST_PointN(_linestring, index)),
    GREATEST(
        discard3points(
            ST_PointN(foo.linestring, index-1),
            ST_PointN(foo.linestring, index),
            ST_PointN(foo.linestring, index+1)
        ),
        discard3points(
            ST_PointN(foo.linestring, index+1),
            ST_PointN(foo.linestring, index),
            ST_PointN(foo.linestring, index-1)
        )
    ) AS d,
    type,
    {3},
    index
FROM (
    SELECT
        id,
        linestring AS _linestring,
        ST_Transform(linestring, {4}) AS linestring,
        generate_series(2, ST_NPoints(linestring)-1) AS index,
        tags->'{1}' AS type
    FROM
        {0}ways AS ways
    WHERE
        tags != ''::hstore AND
        tags?'{1}' AND tags->'{1}' IN ('{2}') AND
        ST_NPoints(linestring) >= 4
) AS foo
{5}
WHERE
    {6}
    GREATEST(
        discard3points(
            ST_PointN(foo.linestring, index-1),
            ST_PointN(foo.linestring, index),
            ST_PointN(foo.linestring, index+1)
        ),
        discard3points(
            ST_PointN(foo.linestring, index+1),
            ST_PointN(foo.linestring, index),
            ST_PointN(foo.linestring, index-1)
        )
    ) > 70/2
"""

sql12water1 = """
    LEFT JOIN ways ON
        ways.is_polygon AND
        ways.tags != ''::hstore AND
        ways.tags?'natural' AND
        ways.tags->'natural' = 'water' AND
        ways.tags?'water' AND
        ways.tags->'water' IN ('lake', 'lagoon', 'basin', 'reservoir') AND
        ways.linestring && ST_PointN(foo._linestring, index) AND
        ST_Intersects(ST_MakePolygon(ways.linestring), ST_PointN(foo._linestring, index))
"""

sql12water2 = """
    ways.id IS NULL AND
"""

class Analyser_Osmosis_Way_Approximate(Analyser_Osmosis):

    def __init__(self, config, logger = None):
        Analyser_Osmosis.__init__(self, config, logger)
        highway_values = ("motorway", "trunk", "primary", "secondary")
        if self.config.options and "osmosis_way_approximate" in self.config.options and self.config.options["osmosis_way_approximate"].get("highway"):
            highway_values = self.config.options["osmosis_way_approximate"].get("highway")
        self.tags = ( (10, "railway", ("rail",), '', ''),
                      (20, "waterway", ("river",), sql12water1, sql12water2),
                      (30, "highway", highway_values, '', ''),
                    )
        for t in self.tags:
            self.classs_change[t[0]] = self.def_class(item = 1190, level = 3, tags = ['geom', 'highway', 'railway', 'fix:imagery'],
                title = T_('Approximate geometry of {0}', t[1]),
                detail = T_(
'''Geometry seems to be draw crudely, there is a discrepancy between the
drawing and the real way especially in the curve.'''),
                fix = T_(
'''After checking orthophotos, add nodes or move existing nodes.'''),
                trap = T_(
'''On service ways, train stations, train workshops that may be either a
false positive'''),
                example = T_(
'''![](https://wiki.openstreetmap.org/w/images/9/9d/Osmose-eg-error-1190.png)

`railway=rail` crudely drawn.'''))

        self.callback10 = lambda res: {"class":res[4], "subclass":res[5], "data":[self.way_full, self.positionAsText], "text": T_("{0} deviation of {1}m", res[3], res[2])}

    def analyser_osmosis_full(self):
        self.run(sql10)
        self.run(sql11)
        for t in self.tags:
            self.run(sql12.format("", t[1], "', '".join(t[2]), t[0], self.config.options.get("proj"), t[3], t[4]), self.callback10)

    def analyser_osmosis_diff(self):
        self.run(sql10)
        self.run(sql11)
        for t in self.tags:
            self.run(sql12.format("touched_", t[1], "', '".join(t[2]), t[0], self.config.options.get("proj"), t[3], t[4]), self.callback10)
