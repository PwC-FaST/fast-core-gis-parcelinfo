var express = require('express');
var router = express.Router();
var axios = require('axios');

host = process.env.MONGODB_HOST || 'localhost'
port = process.env.MONGODB_PORT || 27017
db = process.env.TARGET_DB || 'fast'
lpisCollection = process.env.LPIS_COLLECTION || 'lpis'

urlPrefix = process.env.FRONTEND_URL_PREFIX || '/'

geojson2gisinfoServiceHost = process.env.GIS_INFO_SERVICE_HOST || 'localhost'
geojson2gisinfoServicePort = process.env.GIS_INFO_STATS_SERVICE_PORT || '8080'
geojson2gisinfoWS = 'http://' + geojson2gisinfoServiceHost + ':' + geojson2gisinfoServicePort;

geojson2socinfoServiceHost = process.env.SOC_INFO_SERVICE_HOST || 'localhost'
geojson2socinfoServicePort = process.env.SOC_INFO_SERVICE_PORT || '8081'
geojson2socinfoWS = 'http://' + geojson2socinfoServiceHost + ':' + geojson2socinfoServicePort;

geojson2hydroinfoServiceHost = process.env.HYDRO_INFO_SERVICE_HOST || 'localhost'
geojson2hydroinfoServicePort = process.env.HYDRO_INFO_SERVICE_PORT || '8082'
geojson2hydroinfoWS = 'http://' + geojson2hydroinfoServiceHost + ':' + geojson2hydroinfoServicePort;

geojson2naturainfoServiceHost = process.env.NATURA2000_INFO_SERVICE_HOST || 'localhost'
geojson2naturainfoServicePort = process.env.NATURA2000_INFO_SERVICE_PORT || '8083'
geojson2naturainfoWS = 'http://' + geojson2naturainfoServiceHost + ':' + geojson2naturainfoServicePort;

geojson2topsoilinfoServiceHost = process.env.TOPSOIL_INFO_SERVICE_HOST || 'localhost'
geojson2topsoilinfoServicePort = process.env.TOPSOIL_INFO_SERVICE_PORT || '8084'
geojson2topsoilinfoWS = 'http://' + geojson2topsoilinfoServiceHost + ':' + geojson2topsoilinfoServicePort;

if (urlPrefix.slice(-1) != '/') {
    urlPrefix += '/'
}

// Mongoose import
var mongoose = require('mongoose');

// Mongoose connection to MongoDB
mongoose.connect('mongodb://' + host + ':' + port + '/' + db, { useNewUrlParser: true }, function (error) {
    if (error) {
        console.log(error);
    }
});

// Mongoose Schema definition
var Schema = mongoose.Schema;

var ParcelSchema = new Schema({
    _id: Schema.Types.String,
    geometry: {
      coordinates: []
    }
})

// Mongoose Model definition
var Parcel = mongoose.model('JString', ParcelSchema, lpisCollection);


router.post('/gis', function (req, res) {
    if (req) {
       const parcelIds = req.body;

        if (parcelIds.length == 0) {
            return res.status(400).send({ message: "No parcel given !"})
        }

        Parcel.find({_id: { $in: parcelIds} }, function (err, parcels) {
            if (err) {
                res.status(500).send({ "error": err })
            } else {

                if (parcelIds.length != parcels.length) {
                    foundParcels = parcels.map(p => p.toJSON()._id)
                    return res.status(400).send({
                        message: 'At least one parcel has not been found !',
                        parcels: parcelIds.filter(id => ! foundParcels.includes(id))})
                }

                fc = {
                    type: "FeatureCollection",
                    features: parcels.map(p => p.toJSON())
                }

                axios.post(geojson2gisinfoWS,fc)
                    .then(function (response) {
                        res.setHeader('content-type', response.headers['content-type']);
                        res.send(response.data);
                    })
                    .catch(function (err) {
                        if (err.response) {
                            // that falls out of the range of 2xx
                            console.log(err)
                            res.status(500).send({
                                error: "Error while processing parcel stats, " + err.response.data})
                        } else if (err.request) {
                            // The request was made but no response was received
                            console.log(err.request);
                            res.status(500).send({ error: "Service to process parcel stats not reachable !"})
                        } else {
                            // Something happened in setting up the request that triggered an Error
                            console.log('Error', err.message);
                            res.status(500).send()
                        }
                    })
            }
        })
    }
})

router.post('/soc', function (req, res) {
    if (req) {
        const parcelIds = req.body;

        if (parcelIds.length == 0) {
            return res.status(400).send({ message: "No parcel given !"})
        }

        Parcel.find({_id: { $in: parcelIds} }, function (err, parcels) {
            if (err) {
                res.status(500).send({ "error": err })
            } else {

                if (parcelIds.length != parcels.length) {
                    foundParcels = parcels.map(p => p.toJSON()._id)
                    return res.status(400).send({
                        message: 'At least one parcel has not been found !',
                        parcels: parcelIds.filter(id => ! foundParcels.includes(id))})
                }

                let promises = []

                parcels.map(p => promises.push(axios.post(geojson2socinfoWS,p.toJSON())))

                axios.all(promises)
                    .then(axios.spread(function (...args) {
                        result = args.map(function(r) {
                            feature = JSON.parse(r.config.data)
                            r.data._id = feature._id
                            return r.data
                        })
                        res.send(result)
                    }))
                    .catch(function (err) {
                        if (err.response) {
                            // that falls out of the range of 2xx
                            console.log(err)
                            res.status(500).send({
                                error: "Error while processing SOC approximation !"})
                        } else if (err.request) {
                            // The request was made but no response was received
                            console.log(err.request);
                            res.status(500).send({ error: "Error while processing SOC approximation !"})
                        } else {
                            // Something happened in setting up the request that triggered an Error
                            console.log('Error', err.message);
                            res.status(500).send()
                        }
                    })
            }
        })
    }
})


router.post('/hydro', function (req, res) {
    if (req) {
        const parcelIds = req.body;

        query = []
        for (p in req.query) {
            query.push(p + '=' + req.query[p])
        }

        if (parcelIds.length == 0) {
            return res.status(400).send({ message: "No parcel given !"})
        }

        Parcel.find({_id: { $in: parcelIds} }, function (err, parcels) {
            if (err) {
                res.status(500).send({ "error": err })
            } else {

                if (parcelIds.length != parcels.length) {
                    foundParcels = parcels.map(p => p.toJSON()._id)
                    return res.status(400).send({
                        message: 'At least one parcel has not been found !',
                        parcels: parcelIds.filter(id => ! foundParcels.includes(id))})
                }

                let promises = []

                parcels.map(p => promises.push(axios.post(geojson2hydroinfoWS + '?' +query.join('&'),p.toJSON())))

                axios.all(promises)
                    .then(axios.spread(function (...args) {
                        result = args.map(function(r) {
                            feature = JSON.parse(r.config.data)
                            r.data._id = feature._id
                            return r.data
                        })
                        res.send(result)
                    }))
                    .catch(function (err) {
                        if (err.response) {
                            // that falls out of the range of 2xx
                            console.log(err)
                            res.status(500).send({
                                error: "Error while retrieving hydro areas nearby !"})
                        } else if (err.request) {
                            // The request was made but no response was received
                            console.log(err.request);
                            res.status(500).send({ error: "Error while retrieving hydro areas nearby !"})
                        } else {
                            // Something happened in setting up the request that triggered an Error
                            console.log('Error', err.message);
                            res.status(500).send()
                        }
                    })
            }
        })
    }
})

router.post('/natura2000', function (req, res) {
    if (req) {
        const parcelIds = req.body;

        query = []
        for (p in req.query) {
            query.push(p + '=' + req.query[p])
        }

        if (parcelIds.length == 0) {
            return res.status(400).send({ message: "No parcel given !"})
        }

        Parcel.find({_id: { $in: parcelIds} }, function (err, parcels) {
            if (err) {
                res.status(500).send({ "error": err })
            } else {

                if (parcelIds.length != parcels.length) {
                    foundParcels = parcels.map(p => p.toJSON()._id)
                    return res.status(400).send({
                        message: 'At least one parcel has not been found !',
                        parcels: parcelIds.filter(id => ! foundParcels.includes(id))})
                }

                let promises = []

                parcels.map(p => promises.push(axios.post(geojson2naturainfoWS + '?' +query.join('&'),p.toJSON())))

                axios.all(promises)
                    .then(axios.spread(function (...args) {
                        result = args.map(function(r) {
                            feature = JSON.parse(r.config.data)
                            r.data._id = feature._id
                            return r.data
                        })
                        res.send(result)
                    }))
                    .catch(function (err) {
                        if (err.response) {
                            // that falls out of the range of 2xx
                            console.log(err)
                            res.status(500).send({
                                error: "Error while retrieving natura2000 areas nearby !"})
                        } else if (err.request) {
                            // The request was made but no response was received
                            console.log(err.request);
                            res.status(500).send({ error: "Error while retrieving natura2000 areas nearby !"})
                        } else {
                            // Something happened in setting up the request that triggered an Error
                            console.log('Error', err.message);
                            res.status(500).send()
                        }
                    })
            }
        })
    }
})

router.post('/topsoil', function (req, res) {
    if (req) {
        const parcelIds = req.body;

        query = []
        for (p in req.query) {
            query.push(p + '=' + req.query[p])
        }

        if (parcelIds.length == 0) {
            return res.status(400).send({ message: "No parcel given !"})
        }

        Parcel.find({_id: { $in: parcelIds} }, function (err, parcels) {
            if (err) {
                res.status(500).send({ "error": err })
            } else {

                if (parcelIds.length != parcels.length) {
                    foundParcels = parcels.map(p => p.toJSON()._id)
                    return res.status(400).send({
                        message: 'At least one parcel has not been found !',
                        parcels: parcelIds.filter(id => ! foundParcels.includes(id))})
                }

                let promises = []

                parcels.map(p => promises.push(axios.post(geojson2topsoilinfoWS + '?' +query.join('&'),p.toJSON())))

                axios.all(promises)
                    .then(axios.spread(function (...args) {
                        result = args.map(function(r) {
                            feature = JSON.parse(r.config.data)
                            r.data._id = feature._id
                            return r.data
                        })
                        res.send(result)
                    }))
                    .catch(function (err) {
                        if (err.response) {
                            // that falls out of the range of 2xx
                            console.log(err)
                            res.status(500).send({
                                error: "Error while retrieving TOPSOIL points nearby !"})
                        } else if (err.request) {
                            // The request was made but no response was received
                            console.log(err.request);
                            res.status(500).send({ error: "Error while retrieving TOPSOIL points nearby !"})
                        } else {
                            // Something happened in setting up the request that triggered an Error
                            console.log('Error', err.message);
                            res.status(500).send()
                        }
                    })
            }
        })
    }
})


router.get('/healthz', function(req,res) {
    status = 200
    if (mongoose.connection.readyState != 1) {
        status = 500
    } else {
        Parcel.findOne(function(err, doc) {
            if (err) {
                status = 500
            }
        })

    }
    res.status(status).send();
});

module.exports = router;
