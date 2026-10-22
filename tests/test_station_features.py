"""Station isolation, exact-hour targets, and future-independent weather histories."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pyspark.sql import SparkSession,functions as F
from station_features import feature_columns,station_history,weather_history


class StationWindowChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark=(SparkSession.builder.master('local[2]').appName('Station-window-checks')
                   .config('spark.sql.session.timeZone','Asia/Shanghai').config('spark.sql.shuffle.partitions','2').getOrCreate())
        cls.spark.sparkContext.setLogLevel('ERROR')
    @classmethod
    def tearDownClass(cls):cls.spark.stop()

    def test_labels_and_lags_stay_in_the_same_station(self):
        f=self.spark.createDataFrame([('A','2023-01-01 00:00:00',10.),('A','2023-01-01 01:00:00',None),
                                     ('A','2023-01-01 02:00:00',20.),('B','2023-01-01 00:00:00',200.),
                                     ('B','2023-01-01 01:00:00',201.),('B','2023-01-01 02:00:00',202.)],
                                    'station_id string,ts string,pm25 double').withColumn('ts',F.to_timestamp('ts'))
        result={(r.station_id,str(r.ts)):r for r in station_history(f).collect()}
        origin=result[('A','2023-01-01 00:00:00')]
        self.assertIsNone(origin.label_h1);self.assertEqual(origin.label_h2,20.)
        self.assertIsNone(result[('A','2023-01-01 02:00:00')].pm25_lag_1h)
        self.assertEqual(result[('B','2023-01-01 00:00:00')].label_h1,201.)

    def test_weather_windows_ignore_future_values(self):
        f=self.spark.range(96).withColumn('city_id',F.lit('beijing')).withColumn('ts',F.expr("timestamp'2023-01-01 00:00:00' + id * interval 1 hour"))
        for n in ['temperature_2m','relative_humidity_2m','surface_pressure','wind_speed_10m']:f=f.withColumn(n,F.col('id').cast('double'))
        f=f.withColumn('precipitation',F.lit(1.)).withColumn('wind_direction_10m',F.lit(0.))
        original=weather_history(f).filter('id=72').first().asDict()
        changed=f.withColumn('temperature_2m',F.when(F.col('id')>72,99999.).otherwise(F.col('temperature_2m')))
        revised=weather_history(changed).filter('id=72').first().asDict()
        self.assertEqual(original,revised)
        self.assertEqual(original['weather_temperature_2m_lag_72h'],0.)
        self.assertEqual(original['weather_temperature_2m_mean_72h'],36.5)
        self.assertEqual(original['weather_temperature_2m_change_24h'],24.)
        self.assertEqual(original['weather_precipitation_sum_72h'],72.)

    def test_feature_sets_are_unique_and_contain_no_targets(self):
        short,long=feature_columns(False),feature_columns(True)
        self.assertTrue(set(short)<set(long));self.assertEqual(len(long),len(set(long)))
        self.assertFalse(any('label' in n or 'target' in n for n in long))
        self.assertIn('weather_wind_speed_10m_lag_72h',long)


if __name__=='__main__':unittest.main()
