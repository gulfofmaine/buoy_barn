from forecasts.forecasts.bio.bedford import (
    BedfordWaveDirection,
    BedfordWaveHeight,
    BedfordWavePeriod,
)
from forecasts.forecasts.coastwatch_erddap.gfs import (
    GFSAirTemp,
    GFSWindDirection,
    GFSWindSpeed,
)
from forecasts.forecasts.umass.necofs import (
    NecofsWaveDirection,
    NecofsWaveHeight,
    NecofsWavePeriod,
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
