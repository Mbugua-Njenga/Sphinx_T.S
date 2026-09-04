"""
carbon_credit_calculator.py

Converts satellite-derived vegetation statistics (from gee_processor.py) into an
estimated carbon stock and a credit amount to submit on-chain.

IMPORTANT — methodology disclaimer:
This module implements a simplified, transparent NDVI-to-biomass proxy so the
pipeline is end-to-end runnable. It is NOT an accredited carbon accounting
methodology. Real credit issuance requires:
  - A registered methodology (e.g. Verra VM0042, Gold Standard, CDM AR-ACM0003)
  - Field-calibrated allometric equations or biomass models for the specific
    ecosystem type, ideally with ground-truth plot data
  - Additionality, baseline, leakage, and permanence assessments
  - Third-party verification before issuance

Swap `ndvi_to_biomass_density` for a calibrated model before using this for
anything beyond a technical demo.
"""

from dataclasses import dataclass


# tC/ha at NDVI = 1.0, scaled linearly down to 0 at NDVI = baseline.
# This is a rough proxy, not a calibrated allometric model — see disclaimer above.
MAX_BIOMASS_CARBON_DENSITY_T_PER_HA = 45.0
NDVI_BASELINE = 0.2

CO2_PER_CARBON = 3.6667  # molecular weight ratio CO2/C, standard conversion factor

# Fraction of gross credits withheld as a non-permanence / reversal buffer,
# consistent with common voluntary market practice (typically 10-20%).
BUFFER_POOL_FRACTION = 0.15


@dataclass
class CarbonEstimate:
    area_ha: float
    vegetated_area_ha: float
    mean_ndvi_vegetated: float
    carbon_stock_tC: float
    co2e_gross_tons: float
    buffer_pool_tons: float
    creditable_tons: float


def ndvi_to_biomass_density(ndvi: float) -> float:
    """Linear NDVI-to-carbon-density proxy, clipped to a plausible range."""
    if ndvi is None:
        return 0.0
    scaled = max(0.0, (ndvi - NDVI_BASELINE) / (1.0 - NDVI_BASELINE))
    return scaled * MAX_BIOMASS_CARBON_DENSITY_T_PER_HA


def calculate_credits(parcel_stats: dict) -> CarbonEstimate:
    """Take the dict returned by gee_processor.compute_parcel_stats and produce
    a CarbonEstimate with the creditable tonnage to mint on-chain."""
    vegetated_area_ha = parcel_stats["vegetated_area_ha"]
    mean_ndvi_vegetated = parcel_stats.get("mean_ndvi_vegetated") or 0.0

    density_t_per_ha = ndvi_to_biomass_density(mean_ndvi_vegetated)
    carbon_stock_tC = density_t_per_ha * vegetated_area_ha
    co2e_gross_tons = carbon_stock_tC * CO2_PER_CARBON

    buffer_pool_tons = co2e_gross_tons * BUFFER_POOL_FRACTION
    creditable_tons = co2e_gross_tons - buffer_pool_tons

    return CarbonEstimate(
        area_ha=parcel_stats["area_ha"],
        vegetated_area_ha=vegetated_area_ha,
        mean_ndvi_vegetated=mean_ndvi_vegetated,
        carbon_stock_tC=round(carbon_stock_tC, 3),
        co2e_gross_tons=round(co2e_gross_tons, 3),
        buffer_pool_tons=round(buffer_pool_tons, 3),
        creditable_tons=round(creditable_tons, 3),
    )


if __name__ == "__main__":
    example_stats = {
        "area_ha": 12.4,
        "vegetated_area_ha": 10.1,
        "vegetated_fraction": 0.81,
        "mean_ndvi": 0.52,
        "mean_ndvi_vegetated": 0.61,
    }
    estimate = calculate_credits(example_stats)
    print(estimate)
