import os
import math
import json
import threading
import requests
import traceback

import geojson
import pyproj
import shapely_geojson

from pymongo import MongoClient
from shapely.geometry import shape
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

        # MongoDB infos
        db = FunctionConfig.target_db
        collection = FunctionConfig.soc_collection
        client = FunctionState.mongodb_client

        # MongoDB SOC collection
        soc = client[db][collection]

        # parse request's body
        feature = Helpers.parse_body(context,body)

        # get original CRS of the feature
        props = feature['properties']
        if not ('crs' in props or 'legal_crs' in props):
            context.logger.warn_with('CRS of the feature not found in properties, please specify one !')
            raise NuclioResponseError(
                'CRS of the feature not found in properties, please specify one !',requests.codes.bad)
        crs_attr = 'legal_crs' if 'legal_crs' in props else 'crs'
        if 'type' in props[crs_attr] and props[crs_attr]['type'] == 'EPSG':
            code = props[crs_attr]['properties']['code']
            epsg_crs = "{0}:{1}".format(props[crs_attr]['type'],code)

        # set the according reprojection lambda function
        source = Proj(init=FunctionConfig.source_crs)
        context.logger.info("Source CRS: {0}".format(FunctionConfig.source_crs))
        target = Proj(init=epsg_crs)
        context.logger.info("Source CRS: {0}".format(epsg_crs))
        reproject = lambda x,y: pyproj.transform(source,target,x,y)

        ## get colocated SOC data within a buffer of the requested feature
        res = FunctionConfig.soc_resolution
        buf = math.degrees(res/(6371 * 1000)) # in degree as we expected a EPSG:4326 CRS (WGS84)
        search = shape(feature['geometry']).buffer(buf)

        # get SOC raster data
        geom = geojson.loads(shapely_geojson.dumps(search))
        soc_data = list(soc.find({
            "geometry": { 
                "$geoWithin": { 
                    "$geometry": geom
                } 
            } 
        }, { "_id": 0 }))

        # get reprojected pixels
        soc_pixels = [
            transform(reproject,shape(p['geometry'])).buffer(res/2,cap_style=3) 
            for p in soc_data
        ]

        # inject SOC value (elevation/z)
        soc_attr = 'soc'
        for i, v in enumerate(soc_data):
            soc_pixels[i].value = v['properties'][soc_attr]

        # reproject the requested feature to original CRS add add a buffer to smooth the computed result
        parcel = transform(reproject,shape(feature['geometry'])).buffer(res/4)
        s1, s2 = 0, 0
        # process a weighted value according to the parcel's footprint on each intersected pixel
        for px in soc_pixels:
            area = parcel.intersection(px).area
            s1 += area * px.value
            s2 += area
        # update the parcel with the weighted value if at least one pixel intersects it
        if s2 != 0:
            soc_average = round(s1/s2,6) # arbitrary

        context.logger.info("'{0}' soc pixels processed".format(len(soc_data)))

    except NuclioResponseError as error:
        return error.as_response(context)

    except Exception as error:
        context.logger.warn_with('Unexpected error occurred, responding with internal server error',
            exc=str(error))
        message = 'Unexpected error occurred: {0}\n{1}'.format(error, traceback.format_exc())
        return NuclioResponseError(message).as_response(context)

    return context.Response(body=json.dumps({ 'soc': soc_average }),
                            headers={},
                            content_type='application/json',
                            status_code=requests.codes.ok)


class FunctionConfig(object):

    source_crs = 'EPSG:4326'

    mongodb_host = None

    mongodb_port = None

    target_db = None

    soc_collection = None

    soc_resolution = None # in meters


class FunctionState(object):

    mongodb_client = None

    done_loading = False


class Helpers(object):

    @staticmethod
    def load_configs():

        FunctionConfig.mongodb_host = os.getenv('MONGODB_HOST','localhost')
        FunctionConfig.mongodb_port = os.getenv('MONGODB_PORT',27017)
        FunctionConfig.target_db = os.getenv('MONGODB_DB','fast')
        FunctionConfig.soc_collection = os.getenv('SOC_MONGODB_COLLECTION')
        FunctionConfig.soc_resolution = int(os.getenv('SOC_RESOLUTION','500'))

    @staticmethod
    def load_mongodb_client():

        host = FunctionConfig.mongodb_host
        port = FunctionConfig.mongodb_port
        uri = "mongodb://{0}:{1}/".format(host,port)
        FunctionState.mongodb_client = MongoClient(uri)

    @staticmethod
    def parse_body(context, body):

        # check if it's a valid GeoJSON
        try:
            geodoc = geojson.loads(json.dumps(body))
        except Exception as error:
            context.logger.warn_with("The provided GeoJSON is not valid.")
            raise NuclioResponseError(
                "The provided GeoJSON is not valid.",requests.codes.bad)

        if not (isinstance(geodoc,geojson.feature.Feature) and geodoc.is_valid):
            context.logger.warn_with("The provided GeoJSON is not of type 'Feature'.")
            raise NuclioResponseError(
                "The provided GeoJSON is not of type 'Feature'.",requests.codes.bad)

        return geodoc

    @staticmethod
    def on_import():

        Helpers.load_configs()
        Helpers.load_mongodb_client()
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
