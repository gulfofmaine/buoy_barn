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
from forecasts.forecasts.umass.necofs import (
    NecofsWaveHeight,
    NecofsWavePeriod,
    NecofsWaveDirection,
)

# from forecasts.forecasts.coastwatch_erddap.wave_watch import GlobalWaveWatchHeight

forecast_list = [
    BedfordWaveDirection(),
    BedfordWaveHeight(),
    BedfordWavePeriod(),
    GFSAirTemp(),
    GFSWindSpeed(),
    GFSWindDirection(),
    # GlobalWaveWatchHeight(),
    NecofsWaveHeight(),
    NecofsWavePeriod(),
    NecofsWaveDirection(),
]
