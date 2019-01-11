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
        collection = FunctionConfig.natura_collection
        client = FunctionState.mongodb_client

        # MongoDB SOC collection
        natura = client[db][collection]

        # parse request's body
        feature = Helpers.parse_body(context,body)

        search_distance = FunctionConfig.default_search_distance
        if 'search' in event.fields:
            search_distance = int(event.fields['search'])

        # Get legal CRS
        props = feature['properties']
        if not ('crs' in props or 'legal_crs' in props):
            context.logger.warn_with('CRS of the feature not found in properties, please specify one !')
            raise NuclioResponseError(
                'CRS of the feature not found in properties, please specify one !',requests.codes.bad)
        crs_attr = 'legal_crs' if 'legal_crs' in props else 'crs'
        if 'type' in props[crs_attr] and props[crs_attr]['type'] == 'EPSG':
            code = props[crs_attr]['properties']['code']
            epsg_crs = "{0}:{1}".format(props[crs_attr]['type'],code)
        context.logger.info("Legal CRS: '{0}'".format(epsg_crs))

        # Reprojection function to legal CRS
        source = Proj(init=FunctionConfig.source_crs)
        target = Proj(init=epsg_crs)
        reproject = lambda x,y: pyproj.transform(source,target,x,y)

        # Get a buffer of the target feature
        buf = math.degrees((search_distance+100)/(6371 * 1000)) # in degree as we expected a EPSG:4326 CRS (WGS84)
        search = shape(feature['geometry']).buffer(buf)

        # Get natura2000 features intersecting the target feature
        natura_features = list(natura.find({
            "geometry": { 
                "$geoIntersects": { 
                    "$geometry": geojson.loads(shapely_geojson.dumps(search))
                } 
            } 
        }))

        # Reprojection of natura2000 geometries in legal CRS
        natura_geoms = [
            transform(reproject,shape(n['geometry']))
            for n in natura_features
        ]

        # Reprojection of target geometry in legal CRS
        parcel = transform(reproject,shape(feature['geometry']))

        for i, f in enumerate(natura_features):
            natura_geoms[i].value = f

        result = []
        for n in natura_geoms:
            d = parcel.distance(n)
            if d <= search_distance:
                r = {
                    "_id": n.value['_id'],
                    "intersects": False,
                    "minDistance": d,
                    "properties": n.value['properties']['natura'],
                    "wktType": n.type.upper()
                }
                r.update(n.value['properties'])
                r.pop('crs')
                r.pop('natura')
                r.pop('version')
                if parcel.intersects(n):
                    i = parcel.intersection(n)
                    r['intersects'] = True
                    r['intersection'] = i.area if i.area else i.length
                result.append(r)

        context.logger.info("'{0}' natura2000 features processed".format(len(natura_features)))

    except NuclioResponseError as error:
        return error.as_response(context)

    except Exception as error:
        context.logger.warn_with('Unexpected error occurred, responding with internal server error',
            exc=str(error))
        message = 'Unexpected error occurred: {0}\n{1}'.format(error, traceback.format_exc())
        return NuclioResponseError(message).as_response(context)

    return context.Response(body=json.dumps({ 'natura2000': result }),
                            headers={},
                            content_type='application/json',
                            status_code=requests.codes.ok)


class FunctionConfig(object):

    source_crs = 'EPSG:4326'

    mongodb_host = None

    mongodb_port = None

    target_db = None

    natura_collection = None

    default_search_distance = None # defaul distance to search natura2000 features within (in meters)


class FunctionState(object):

    mongodb_client = None

    done_loading = False


class Helpers(object):

    @staticmethod
    def load_configs():

        FunctionConfig.mongodb_host = os.getenv('MONGODB_HOST','localhost')
        FunctionConfig.mongodb_port = os.getenv('MONGODB_PORT',27017)
        FunctionConfig.target_db = os.getenv('MONGODB_DB','fast')
        FunctionConfig.natura_collection = os.getenv('NATURA2000_MONGODB_COLLECTION')
        FunctionConfig.default_search_distance = int(os.getenv('NATURA2000_DEFAULT_SEARCH_DISTANCE',100))

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
