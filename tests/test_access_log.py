# from cast.access_log import get_last_request_position
# from cast.access_log import get_dataframe_from_position


# class TestParseAccesslog:
#    def test_get_access_log_position(self, access_log_path, last_request_dummy):
#        position = get_last_request_position(access_log_path, last_request_dummy)
#        assert position == 4
#
#    def test_get_df_from_access_log(self, access_log_path):
#        df = get_dataframe_from_position(access_log_path)
#        assert df.shape == (5, 9)
