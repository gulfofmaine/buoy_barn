/* global ol, MapWidget */
'use strict';

// Registers an additional OpenLayers base-layer builder for Django's admin GIS
// widget (see django.contrib.gis.forms.widgets.OpenLayersWidget / OLMapWidget.js).
// Must load AFTER gis/js/OLMapWidget.js so `MapWidget` already exists.
MapWidget.layerBuilder.esriOcean = () => {
    return new ol.layer.Tile({
        source: new ol.source.XYZ({
            attributions: 'Esri, Garmin, GEBCO, NOAA NGDC, and other contributors',
            maxZoom: 16,
            url: 'https://services.arcgisonline.com/arcgis/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}'
        })
    });
};
