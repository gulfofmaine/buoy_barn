# Generated by Django 2.1.2 on 2018-12-04 16:13

from django.db import migrations, models


def empty_reverse(apps, schema_editor):
    pass


def create_mooring_type(apps, schema_editor):
    MooringType = apps.get_model('deployments', 'MooringType')

    slack = MooringType(name='Slack')
    slack.save()

    tethered = MooringType(name="Tethered")
    tethered.save()


def create_station_type(apps, schema_editor):
    StationType = apps.get_model('deployments', 'StationType')

    for name in ('buoy', 'Surface Mooring', 'ndbc'):
        station = StationType(name=name)
        station.save()


def create_data_type(apps, schema_editor):

    data_types = [
        ("air_temperature","AT","Air Temperature","celsius"),
        ("amps","AMPS","Amps","counts"),
        ("average_wave_period","AWP","Average Wave Period","seconds"),
        ("solar_zenith_angle","SZA","Solar Zenith Angle","radians"),
        ("dew_point_temperature","DEWP","Dewpoint Temperature","celsius"),
        ("direction_of_sea_water_velocity","CDIR","Current Direction","angular_degrees"),
        ("dissolved_oxygen","DO","Dissolved Oxygen","ml/l"),
        ("dominant_wave_period","DWP","Dominant Wave Period","seconds"),
        ("eastward_sea_water_velocity","u","East Velocity Component","cm/s"),
        ("lat_offset","latoff","Latitudinal Offset","angular_minute"),
        ("lon_offset","lonoff","Longitudinal Offset","angular_minute"),
        ("max_visibility","VISMAX","Maximum Visibility","meters"),
        ("mean_wave_direction","MWD","Mean Wave Direction","degrees"),
        ("min_visibility","VISMIN","Minimum Visibility","meters"),
        ("northward_sea_water_velocity","v","North Velocity Component","cm/s"),
        ("oxygen_saturation","DO","Oxygen Saturation","ml/l"),
        ("percent_oxygen_saturation","POXSAT","Percent Oxygen Saturation","percent"),
        ("predicted_sea_water_level","PWL","Predicted level of sea water","m"),
        ("pressure_tendency","PTDY","Pressure Tendency","degrees"),
        ("sea_level_pressure","BARO","Sea Level Pressure","hPa"),
        ("sea_water_density","SIGMAT","Sigma-T","kg/m^3"),
        ("sea_water_level","SWL","Sea water level relative to the mean","m"),
        ("sea_water_salinity","S","Salinity","psu"),
        ("sea_water_speed","CSPD","Current Speed","cm/s"),
        ("sea_water_temperature","WT","Water Temperature","celsius"),
        ("significant_height_of_wind_and_swell_waves","WVHT","Significant Wave Height","m"),
        ("transmissivity_voltage","TRANSV","Transmissivity Voltage","percent"),
        ("transmissivity","TRANS","Transmissivity","percent"),
        ("visibility_in_air","VIS","Visibility","meters"),
        ("wind_direction_kvh","WDIR","Mean Wind Direction","degrees magnetic"),
        ("wind_direction_stddev","WDIRSTD","Wind Direction Standard Deviation","degrees"),
        ("wind_direction_uv_stddev","WDSTDEV","Unit Vector Mean Wind Direction Standard Deviation","degrees"),
        ("wind_direction_uv","WD","Unit Vector Mean Wind Direction","degrees"),
        ("wind_direction_ve_stddev","WDSTD","Vector Averaged Wind Direction Standard Deviation","degrees"),
        ("wind_direction_ve","WD","Vector Averaged Wind Direction","degrees"),
        ("wind_from_direction","WD","Wind Direction","degrees"),
        ("wind_gust","GST","Wind Gust","cm/s"),
        ("wind_min","WMSPD","Wind Minimum Speed","cm/s"),
        ("wind_peak","WPEAK","Wind Peak (1 sec)","cm/s"),
        ("wind_speed_sc","WSPD","Scalar Average Wind Speed","m/s"),
        ("wind_speed_ve","WSPD","Vector Average Wind Speed","m/s"),
        ("wind_speed","WSPD","Wind Speed","m/s"),
        ("wind_speed_and_direction","WS+DIR","Wind Speed and Direction","m/s,degrees"),
        ("chlorophyll","CHL","Chlorophyll","chl/m3"),
        ("par","PAR","Photosynthetically Available Radiation","µE/m2/sec"),
        ("percent_clear_sky","PCTSKY","Percent Clear Sky","percent"),
        ("turbidity","TRBD","Turbidity","ntu"),
        ("count","CNT","COUNT","count"),
        ("sun_icon","SI","Sun Icon","1"),
        ("Ed_PAR","Ed(PAR,0+)","Downwelling Irradiance of PAR (400-700nm)","microE/m^2/s"),
        ("percent_sun","PS","Percent Sun","percent"),
        ("sea_water_electrical_conductivity","COND","Conductivity","siemens/m"),
        ("surface_partial_pressure_of_carbon_dioxide_in_air","PC02","Atmospheric CO2 Partial Pressure","microATM"),
        ("surface_partial_pressure_of_carbon_dioxide_in_sea_water","PC02","Sea Surface CO2 Partial Pressure","microATM"),
        ("max_wave_height","MWH","Maximum Wave Height","m"),
        ("wave_direction_spread","WDS","Wave Direction Spread","degrees"),
        ("significant_wave_height","SWH","Significant Wave Height","m"),
        ("sea_water_pH_reported_on_total_scale","pH","pH (Total)","1"),
        ("sea_water_alkalinity_expressed_as_mole_equivalent","TotAlk","Total Alkalinity","microM/kg"),
        ("attenuation","attn","Beam Attenuation","m-1"),
        ("concentration_of_colored_dissolved_organic_matter_in_sea_water","CDOM","Chromophoric Dissolved Organic Matter","ppbQSE"),
        ("mole_concentration_of_nitrate_in_sea_water","NO3","Nitrate Concentration","microM"),
        ("mole_concentration_of_phosphate_in_sea_water","PO4","Phosphate Concentration","microM/l"),
        ("significant_height_of_wind_and_swell_waves_3","WVHT","Significant Wave Height","m"),
        ("dominant_wave_period_3","DWP","Dominant Wave Period","seconds"),
    ]

    DataType = apps.get_model('deployments', 'DataType')

    for data_type in data_types:
        instance = DataType(standard_name=data_type[0], short_name=data_type[1], long_name=data_type[2], units=data_type[3])
        instance.save()


def create_buffer_type(apps, schema_editor):

    buffers = [
        "doppler",
        "aanderaa",
        "sbe16",
        "doppler.realtime",
        "sbe37.pres",
        "met",
        "aanderaa.o2_percent",
        "sbe16.flntus",
        "doppler.uri",
        "waves.triaxys",
        "optics_a.std_above",
        "waves.mstrain",
        "aanderaa.zpulsep",
        "sbe16.trans4",
        "optics_s.oc_flntus",
        "optics_persun",
        "doppler.bowdoin",
        "sbe37",
        "met.bowdoin",
        "optics_s.oc_flntus_f",
        "aanderaa.o2",
        "sbe16.pres",
        "accelerometer",
        "aanderaa.zpulse",
        "met.short",
        "optics_s.std_flntus",
        "met.uri",
        "sbe16.disox",
        "optics_a.std_above7",
        "optode",
        "optics_s.bowdoin",
        "sbe16.trans",
        "ndbc",
        "optics_s.std_small",
        "aanderaa_z",
        "buoy"]
    
    BufferType = apps.get_model('deployments', 'BufferType')

    for name in buffers:
        buffer = BufferType(name=name)
        buffer.save()

class Migration(migrations.Migration):

    dependencies = [
        ('deployments', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='platform',
            name='nbdc_site_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name='platform',
            name='uscg_light_letter',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AlterField(
            model_name='platform',
            name='uscg_light_num',
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AlterField(
            model_name='platform',
            name='watch_circle_radius',
            field=models.IntegerField(blank=True, null=True),
        ),

        migrations.RunPython(create_mooring_type, empty_reverse),
        migrations.RunPython(create_station_type, empty_reverse),
        migrations.RunPython(create_data_type, empty_reverse),
        migrations.RunPython(create_buffer_type, empty_reverse),
    ]
