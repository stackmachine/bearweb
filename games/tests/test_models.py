import os

from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.base import ContentFile

from games.models import Game, Framework, tubeid


class GamesModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("foo", "bar@example.com", "pass")
        self.other = Framework.objects.create(name="Other")

    def test_youtube_id(self):
        self.assertEqual(24, len(tubeid()))

    def test_get_url(self):
        game = Game.objects.create(owner=self.user, framework=self.other,
                                   name="Foo", slug="foo")
        self.assertTrue(game.get_absolute_url() != "")

    def test_game_first_release(self):
        game = Game.objects.create(owner=self.user, framework=self.other,
                                   name="Foo", slug="foo")
        self.assertEquals("0.1.0", game.next_version())

    def test_game_next_release(self):
        game = Game.objects.create(owner=self.user, framework=self.other,
                                   name="Foo", slug="foo")
        game.release_set.create(version="0.1.0")
        game.release_set.create(version="0.2.0")

        self.assertEquals("0.3.0", game.next_version())

    def test_game_download_links(self):
        game = Game.objects.create(owner=self.user, framework=self.other,
                                   name="Foo", slug="foo")
        game.release_set.create(version="0.1.0")

        links = game.download_links()
        win, osx = links[0], links[1]

        self.assertEquals('Windows', win[0])
        self.assertEquals('OSX', osx[0])

        self.assertIn('http://example.com/games', osx[1])

    def test_release_add_asset(self):
        game = Game.objects.create(owner=self.user, framework=self.other,
                                   name="Foo", slug="foo")
        release = game.release_set.create(version='0.1.0')

        blob = ContentFile('foo')
        blob.name = 'foo.txt'

        asset = release.add_asset(blob)

        path = os.path.join("media", game.uuid, "0.1.0")
        self.assertTrue(asset.blob.url.startswith("/" + path))
