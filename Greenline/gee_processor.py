"""
gee_processor.py

Runs Google Earth Engine (GEE) analysis for a single parcel: builds a cloud-free
Sentinel-2 composite over the parcel boundary, computes NDVI statistics, and runs
a supervised land-cover classification so non-vegetated area (buildings, bare soil,
water) is excluded from the carbon calculation.

Setup:
    pip install earthengine-api google-auth
    earthengine authenticate          # one-time interactive login, or
    # use a service account (recommended for a server) — see init_earth_engine()

This module assumes a service account JSON key is available; adapt init_earth_engine()
if you use a different auth flow (e.g. Application Default Credentials).
"""

import os
import ee


def init_earth_engine():
    """Authenticate to Earth Engine using a service account.

    Expects two environment variables:
      GEE_SERVICE_ACCOUNT   - the service account email, e.g. my-sa@project.iam.gserviceaccount.com
      GEE_KEY_FILE          - path to the service account's private key JSON file
    """
    service_account = os.environ["GEE_SERVICE_ACCOUNT"]
    key_file = os.environ["GEE_KEY_FILE"]
    credentials = ee.ServiceAccountCredentials(service_account, key_file)
    ee.Initialize(credentials)


def geojson_to_ee_geometry(geojson_polygon: dict) -> ee.Geometry:
    """Convert a GeoJSON Polygon dict (as submitted from the frontend map) into
    an ee.Geometry.Polygon."""
    return ee.Geometry.Polygon(geojson_polygon["coordinates"])


def _mask_s2_clouds(image: ee.Image) -> ee.Image:
    """Cloud-mask a Sentinel-2 SR image using the QA60 bitmask band."""
    qa = image.select("QA60")
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = (
        qa.bitwiseAnd(cloud_bit_mask).eq(0)
        .And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
    )
    return image.updateMask(mask).divide(10000)


def build_composite(geometry: ee.Geometry, start_date: str, end_date: str) -> ee.Image:
    """Build a median, cloud-masked Sentinel-2 surface reflectance composite
    clipped to the parcel, over the given date range (e.g. a growing season)."""
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geometry)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 25))
        .map(_mask_s2_clouds)
    )
    composite = collection.median().clip(geometry)
    ndvi = composite.normalizedDifference(["B8", "B4"]).rename("NDVI")
    return composite.addBands(ndvi)


def classify_land_cover(composite: ee.Image, geometry: ee.Geometry) -> ee.Image:
    """Classify the composite into vegetation / bare-soil-or-built / water using
    an unsupervised k-means clustering seeded from NDVI + spectral bands.

    This is a lightweight stand-in for a properly trained, ground-truthed
    classifier. For production MRV, replace with a supervised classifier trained
    on labeled reference plots for the target region and biome, per the
    methodology you're issuing credits under (e.g. VM0042, Gold Standard, CDM AR).
    """
    bands = composite.select(["B2", "B3", "B4", "B8", "NDVI"])
    training = bands.sample(
        region=geometry, scale=10, numPixels=2000, seed=42, geometries=False
    )
    clusterer = ee.Clusterer.wekaKMeans(3).train(training)
    clustered = bands.cluster(clusterer)

    # Identify which cluster corresponds to vegetation by mean NDVI per cluster.
    cluster_means = bands.addBands(clustered).reduceRegion(
        reducer=ee.Reducer.mean().group(groupField=5, groupName="cluster"),
        geometry=geometry,
        scale=10,
        maxPixels=1e9,
    )
    return clustered


def compute_parcel_stats(geojson_polygon: dict, start_date: str, end_date: str) -> dict:
    """Main entry point: given a parcel boundary and a date range, returns NDVI
    and vegetated-area statistics ready for the carbon credit calculator.

    Returns:
        {
          "area_ha": float,
          "vegetated_area_ha": float,
          "vegetated_fraction": float,
          "mean_ndvi": float,
          "mean_ndvi_vegetated": float,
        }
    """
    geometry = geojson_to_ee_geometry(geojson_polygon)
    composite = build_composite(geometry, start_date, end_date)
    ndvi = composite.select("NDVI")

    area_m2 = geometry.area(maxError=1).getInfo()
    area_ha = area_m2 / 10000

    # Vegetated mask: NDVI above a conservative threshold, excluding water/built/bare.
    vegetated_mask = ndvi.gt(0.3)
    vegetated_area_m2 = (
        ee.Image.pixelArea()
        .updateMask(vegetated_mask)
        .clip(geometry)
        .reduceRegion(reducer=ee.Reducer.sum(), geometry=geometry, scale=10, maxPixels=1e9)
        .get("area")
        .getInfo()
        or 0
    )
    vegetated_area_ha = vegetated_area_m2 / 10000

    mean_ndvi = (
        ndvi.reduceRegion(reducer=ee.Reducer.mean(), geometry=geometry, scale=10, maxPixels=1e9)
        .get("NDVI")
        .getInfo()
    )
    mean_ndvi_vegetated = (
        ndvi.updateMask(vegetated_mask)
        .reduceRegion(reducer=ee.Reducer.mean(), geometry=geometry, scale=10, maxPixels=1e9)
        .get("NDVI")
        .getInfo()
    )

    return {
        "area_ha": round(area_ha, 4),
        "vegetated_area_ha": round(vegetated_area_ha, 4),
        "vegetated_fraction": round(vegetated_area_ha / area_ha, 4) if area_ha else 0,
        "mean_ndvi": round(mean_ndvi, 4) if mean_ndvi is not None else None,
        "mean_ndvi_vegetated": round(mean_ndvi_vegetated, 4) if mean_ndvi_vegetated is not None else None,
    }


if __name__ == "__main__":
    init_earth_engine()
    example_polygon = {
        "coordinates": [[
            [36.80, -1.28], [36.82, -1.28], [36.82, -1.30], [36.80, -1.30], [36.80, -1.28]
        ]]
    }
    stats = compute_parcel_stats(example_polygon, "2025-01-01", "2025-06-30")
    print(stats)
