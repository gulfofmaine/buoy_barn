from forecasts.forecasts.neracoos_erddap.bedford import (
    BedfordWaveHeight,
    BedfordWavePeriod,
    BedfordWaveDirection,
)
from forecasts.forecasts.coastwatch_erddap.gfs import (
    GFSAirTemp,
    GFSWindSpeed,
    GFSWindDirection,
)

forecast_list = [
    BedfordWaveDirection(),
    BedfordWaveHeight(),
    BedfordWavePeriod(),
    GFSAirTemp(),
    GFSWindSpeed(),
    GFSWindDirection(),
]
