import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import shared_store
from skill import data as skill_data


class TestSharedStoreAndData(unittest.TestCase):
    def setUp(self):
        shared_store._store = None
        shared_store._version = 0
        shared_store._by_player.clear()
        shared_store._device_players.clear()
        with skill_data._meta_lock:
            skill_data._device_meta_sig.clear()

    def test_extract_player_key(self):
        self.assertEqual(
            shared_store.extract_player_key(
                'http://192.168.1.10:8097/flow/abc/Kitchen%20show/123/Kitchen%20show.flac'
            ),
            'Kitchen show',
        )
        self.assertEqual(
            shared_store.extract_player_key(
                'https://ma.example.com/single/s1/q1/i1/Living%20Room%20Echo.mp3?token=1'
            ),
            'Living Room Echo',
        )
        self.assertIsNone(shared_store.extract_player_key(''))

    def test_per_player_isolation_and_change_tracking(self):
        shared_store.put_ma_stream(
            'http://192.168.1.10:8097/flow/s1/Kitchen%20show/t1/Kitchen%20show.flac',
            title='Track One',
            artist='Artist A',
            album='Album A',
            image_url='http://192.168.1.10:8095/imageproxy/abcdef0123456789?size=512&fmt=jpg',
        )
        res1 = skill_data.get_latest(device_id='dev-show', prefer_latest=True)
        self.assertTrue(res1['changed'])
        self.assertEqual(
            res1['info']['audioSources'],
            'http://192.168.1.10:8097/flow/s1/Kitchen%20show/t1/Kitchen%20show.mp3',
        )
        shared_store.bind_device_player('dev-show', 'Kitchen show')

        # Initial MetadataRefresh sees no change since PlayAudio already loaded Track One
        r_poll1 = skill_data.get_latest(device_id='dev-show', track_changes=True)
        self.assertFalse(r_poll1['changed'])

        # Another player receives a stream; Kitchen show APL refresh must stay on Track One
        shared_store.put_ma_stream(
            'http://192.168.1.10:8097/flow/s2/Living%20Echo/t2/Living%20Echo.flac',
            title='Doorbell',
        )
        r_show_after = skill_data.get_latest(device_id='dev-show', track_changes=True)
        self.assertFalse(r_show_after['changed'])
        self.assertEqual(r_show_after['info']['primaryText'], 'Track One')

        # Advancing Kitchen show to Track Two triggers changed=True for dev-show only
        shared_store.put_ma_stream(
            'http://192.168.1.10:8097/flow/s1/Kitchen%20show/t3/Kitchen%20show.flac',
            title='Track Two',
            artist='Artist B',
            album='Album B',
        )
        r_show_next = skill_data.get_latest(device_id='dev-show', track_changes=True)
        self.assertTrue(r_show_next['changed'])
        self.assertEqual(r_show_next['info']['primaryText'], 'Track Two')

        # Fresh PlayAudio on the Echo Dot selects the latest stream unless mapped otherwise
        shared_store.put_ma_stream(
            'http://192.168.1.10:8097/flow/s2/Living%20Echo/t4/Living%20Echo.flac',
            title='Doorbell',
        )
        r_dot = skill_data.get_latest(device_id='dev-dot', prefer_latest=True)
        self.assertEqual(r_dot['info']['primaryText'], 'Doorbell')
        self.assertEqual(
            r_dot['info']['audioSources'],
            'http://192.168.1.10:8097/flow/s2/Living%20Echo/t4/Living%20Echo.mp3',
        )

    def test_build_info_dict_quotes_without_double_encoding(self):
        built = skill_data._build_info_dict({
            'streamUrl': "http://192.168.1.10:8097/flow/s1/Bob's Room/t1/Bob's%20Room.FLAC",
            'title': 'Song',
            'imageUrl': 'http://192.168.1.10:8095/imageproxy/abcdef0123456789?size=512&fmt=jpg',
        })
        self.assertEqual(
            built['audioSources'],
            'http://192.168.1.10:8097/flow/s1/Bob%27s%20Room/t1/Bob%27s%20Room.mp3',
        )


try:
    from skill import util as skill_util
    _HAS_SKILL_UTIL = True
except ImportError:
    _HAS_SKILL_UTIL = False


@unittest.skipUnless(_HAS_SKILL_UTIL, 'skill.util dependencies not installed in host environment')
class TestSkillUtilRewrite(unittest.TestCase):
    def setUp(self):
        self._orig_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_imageproxy_precedence_over_ma_hostname(self):
        os.environ['IMAGE_PROXY_VIA_SKILL'] = 'true'
        os.environ['SKILL_HOSTNAME'] = 'skill.example.com'
        os.environ['MA_HOSTNAME'] = 'stream.example.com'
        url = 'http://192.168.1.10:8095/imageproxy/abcdef0123456789abcdef0123456789?size=512&fmt=jpg'
        self.assertEqual(
            skill_util.rewrite_apl_image_url(url),
            'https://skill.example.com/imageproxy/abcdef0123456789abcdef0123456789?size=512&fmt=jpg',
        )

    def test_fallback_to_ma_hostname_when_proxy_disabled(self):
        os.environ['IMAGE_PROXY_VIA_SKILL'] = 'false'
        os.environ['SKILL_HOSTNAME'] = 'skill.example.com'
        os.environ['MA_HOSTNAME'] = 'ma.example.com'
        url = 'http://192.168.1.10:8095/imageproxy/abcdef0123456789?size=512&fmt=jpg'
        self.assertEqual(
            skill_util.rewrite_apl_image_url(url),
            'https://ma.example.com/imageproxy/abcdef0123456789?size=512&fmt=jpg',
        )


if __name__ == '__main__':
    unittest.main()
