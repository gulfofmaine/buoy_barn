from django.contrib.gis.forms.widgets import OSMWidget


class EsriOceanBasemapWidget(OSMWidget):
    """OpenLayers admin map widget using Esri's World Ocean Basemap instead of OSM.

    OSM tiles started returning 403s in production because our Referrer-Policy
    strips the Referer header on cross-origin tile requests, and osm.org's tile
    usage policy requires one. Esri's Ocean basemap has no such requirement.
    """

    base_layer = "esriOcean"

    class Media:
        # extend=False: declare the full ordered list rather than relying on
        # Django's Media merge across the class hierarchy, which does not
        # reliably keep our file after OLMapWidget.js (observed inserting it
        # between ol.js and OLMapWidget.js instead), breaking the
        # MapWidget.layerBuilder registration this file depends on.
        extend = False
        css = {
            "all": (
                "https://cdn.jsdelivr.net/npm/ol@v7.2.2/ol.css",
                "gis/css/ol3.css",
            ),
        }
        js = (
            "https://cdn.jsdelivr.net/npm/ol@v7.2.2/dist/ol.js",
            "gis/js/OLMapWidget.js",
            "deployments/js/esri_ocean_basemap.js",
        )
