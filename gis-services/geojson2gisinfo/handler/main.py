import os
import json
import threading
import requests
import traceback

import geojson
import pyproj

from shapely.geometry import shape, GeometryCollection
from shapely.ops import transform
from pyproj import Proj


def handler(context, event):

    b = event.body
    if not isinstance(b, dict):
        body = json.loads(b.decode('utf-8-sig'))
    else:
        body = b
    
    context.logger.info("Event received !")

    try:

        # if we're not ready to handle this request yet, deny it
        if not FunctionState.done_loading:
            context.logger.warn_with('Function not ready, denying request !')
            raise NuclioResponseError(
                'The service is loading and is temporarily unavailable.',requests.codes.unavailable)

        # parse the GeoJSON as a feature_collection
        doc = Helpers.parse_body(context,body)

        centroid = Helpers.centroid

        # get features
        features = doc['features']

        # check if all features have the same CRS
        # only EPSG codes are supported for now
        crs = None
        for feature in features:
            crs_attribute = 'crs'
            properties = feature['properties']
            if 'legal_crs' in properties:
                crs_attribute = 'legal_crs'
            if crs_attribute in properties and \
                'type' in properties[crs_attribute] and properties[crs_attribute]['type'] == 'EPSG':
                code = properties[crs_attribute]['properties']['code']
                c = "{0}:{1}".format(properties[crs_attribute]['type'],code)
                if not crs: 
                    crs = c
                elif crs != c:
                    context.logger.warn_with('Features have different CRS !')
                    raise NuclioResponseError(
                        'features have different CRS !',requests.codes.bad)
            else: 
                context.logger.warn_with('A feature has no original CRS !')
                raise NuclioResponseError(
                    'a feature has no original CRS !',requests.codes.bad)

        # set the according reprojection function
        reproject = lambda x,y: pyproj.transform(Proj(init=FunctionConfig.source_crs),Proj(init=crs),x,y)

        # load features as shapely geometry 
        geometries = [shape(f['geometry']) for f in features]

        gc = GeometryCollection(geometries)
        reproj_gc = transform(reproject,gc)

        # build the result
        output = {
            "aggregated": {
                "area": reproj_gc.area,
                "perimeter": reproj_gc.length,
                "centroid": [
                    centroid(gc,crs=FunctionConfig.source_crs),
                    centroid(reproj_gc,crs,True)],
                "center": [
                    centroid(gc.envelope,crs=FunctionConfig.source_crs),
                    centroid(reproj_gc.envelope,crs,True)],
                }
        }

        details = []
        for i, f in enumerate(features):
            g = geometries[i]
            rg = transform(reproject,g)
            details.append({
                "_id": f['_id'],
                "area": rg.area,
                "perimeter": rg.length,
                "centroid": [
                    centroid(g,FunctionConfig.source_crs),
                    centroid(rg,crs,True)],
                "center": [
                    centroid(g.envelope,crs=FunctionConfig.source_crs),
                    centroid(rg.envelope,crs,True)]
            })
        output['details'] = details

        context.logger.info("'{0}' features processed".format(len(features)))

    except NuclioResponseError as error:
        return error.as_response(context)

    except Exception as error:
        context.logger.warn_with('Unexpected error occurred, responding with internal server error',
            exc=str(error))
        message = 'Unexpected error occurred: {0}\n{1}'.format(error, traceback.format_exc())
        return NuclioResponseError(message).as_response(context)

    return context.Response(body=output,
                            headers={},
                            content_type='application/json',
                            status_code=requests.codes.ok)


class FunctionConfig(object):

    source_crs = 'EPSG:4326'


class FunctionState(object):

    done_loading = False


class Helpers(object):

    @staticmethod
    def centroid(shape, crs=None, original=False):
        c = shape.centroid.xy
        r = {
            "crs":crs,
            "original": original,
            "coords": [c[0][0],c[1][0]] 
        }
        return r

    @staticmethod
    def parse_body(context, body):

        # check if it's a valid GeoJSON
        try:
            geodoc = geojson.loads(json.dumps(body))
        except Exception as error:
            context.logger.warn_with("Loading body's request as a GeoJSON failed.")
            raise NuclioResponseError(
                "Loading body's request as a GeoJSON failed.",requests.codes.bad)

        if not (isinstance(geodoc,geojson.feature.FeatureCollection) and geodoc.is_valid):
            context.logger.warn_with("The provided GeoJSON is not a valid 'FeatureCollection'.")
            raise NuclioResponseError(
                "The provided GeoJSON is not a valid 'FeatureCollection'.",requests.codes.bad)

        return geodoc

    @staticmethod
    def on_import():

        FunctionState.done_loading = True


class NuclioResponseError(Exception):

    def __init__(self, description, status_code=requests.codes.internal_server_error):
        self._description = description
        self._status_code = status_code

    def as_response(self, context):
        return context.Response(body=self._description,
                                headers={},
                                content_type='text/plain',
                                status_code=self._status_code)


t = threading.Thread(target=Helpers.on_import)
t.start()
