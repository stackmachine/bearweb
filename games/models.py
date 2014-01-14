import binascii
import hashlib
import os

from django.dispatch import receiver
from django.db import models
from django.db.models.signals import post_save
from django.conf import settings

from subdomains.utils import reverse
from PIL import Image, ImageDraw

from core import tasks


def tubeid():
    """Return an 11 character identifier. Does not guaruntee uniqueness"""
    return binascii.hexlify(os.urandom(12))


class Framework(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    name = models.CharField(max_length=128)

    def __unicode__(self):
        return self.name

_PUBLIC_CHOICES = ((True, 'Public'), (False, 'Private'))
_PUBLIC_HELP = "Public games can be downloaded for free without paying"


class Game(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL)
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    uuid = models.CharField(max_length=24, db_index=True, unique=True)
    framework = models.ForeignKey(Framework)
    public = models.BooleanField(default=False, help_text=_PUBLIC_HELP,
                                 choices=_PUBLIC_CHOICES)

    def __unicode__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.uuid:
            self.uuid = tubeid()
        super(Game, self).save(*args, **kwargs)

    def download_links(self):
        def fullurl(uuid, platform):
            # FIXME: Make this link SSL
            return reverse('download', args=[uuid, platform])

        return [
            ('Windows', fullurl(self.uuid, 'windows')),
            ('OSX', fullurl(self.uuid, 'osx')),
        ]

    def icon_url(self):
        return reverse("identicon", kwargs={"uuid": self.uuid})

    def identicon(self, size):
        im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)

        digest = hashlib.md5(self.uuid).hexdigest()

        icon = digest[:28]
        hex_color = digest[26:]
        color = (int(hex_color[:2], 16),
                 int(hex_color[2:4], 16),
                 int(hex_color[4:6], 16))
        step = size / 7

        print step

        for i, value in enumerate(icon):
            if int(value, 16) % 2 == 0:
                x = (i % 4) * step
                z = (6 - (i % 4)) * step
                y = (i / 4) * step
                draw.rectangle([z, y, z + step - 1, y + step - 1], fill=color)
                draw.rectangle([x, y, x + step - 1, y + step - 1], fill=color)

        del draw  # I'm done drawing so I don't need this anymore

        return im

    def appcast(self):
        items = []

        for release in self.release_set.order_by('-created'):
            items.append(release.appcast())

        return {
            'description': 'Eventually put game description here',
            'items': items,
        }

    def latest_release(self):
        return self.release_set.order_by('-created')[0]

    def get_absolute_url(self):
        return reverse("games:view", subdomain='manage',
                       kwargs={"uuid": self.uuid})

    def next_version(self):
        """If the game has no releases, return 0.1.0. If the game does have a
        release, return the next minor version.
        """
        try:
            release = self.release_set.order_by('-created')[0]
        except IndexError:
            return "0.1.0"

        major, minor, bugfix = release.version.split(".")

        return "{}.{}.{}".format(major, int(minor) + 1, bugfix)

    class Meta:
        unique_together = ("owner", "slug")


@receiver(post_save, sender=Game)
def track_create_game(sender, instance, created, **kwargs):
    if created:
        tasks.track.delay(instance.owner.pk, 'Create Game', game=instance.slug,
                          distinct_id=instance.owner.username)


class Release(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    game = models.ForeignKey(Game)
    version = models.CharField(max_length=14)
    love_version = models.CharField(max_length=14, default="0.8.0")
    uuid = models.CharField(max_length=24, db_index=True, unique=True)

    def save(self, *args, **kwargs):
        if not self.uuid:
            self.uuid = tubeid()
        super(Release, self).save(*args, **kwargs)

    class Meta:
        unique_together = ("game", "version")

    def add_asset(self, django_file, tag=''):
        return self.asset_set.create(tag=tag, blob=django_file)

    # FIXME: Reduntant?
    def windows_url(self):
        asset = self.get_asset('windows')

        if asset is None:
            return ""

        return asset.blob.url.replace("https://", "http://")

    # FIXME: Reduntant?
    def osx_url(self):
        asset = self.get_asset('osx')

        if asset is None:
            return ""

        return asset.blob.url.replace("https://", "http://")

    def appcast(self):
        osx_asset = self.get_asset('osx')
        exe_asset = self.get_asset('exe')

        platforms = []

        if osx_asset:
            platforms.append({
                'name': 'macosx',
                'arch': 'universal',
                'files': [osx_asset.appcast()],
            })

        if exe_asset:
            platforms.append({
                'name': 'windows',
                'arch': 'i386',
                'files': [exe_asset.appcast()],
            })

        return {
            'changelog': '',
            'platforms': platforms,
            'published': '',
            'title': '{} | Version {}'.format(self.game.name, self.version),
            'version': self.version,
        }

    def get_asset(self, tag):
        # FIXME: This will fail if there are other uploaded files
        try:
            return self.asset_set.filter(tag=tag)[0]
        except IndexError:
            return None

    def __unicode__(self):
        return "{} {}".format(self.game.name, self.version)


@receiver(post_save, sender=Release)
def track_create_release(sender, instance, created, **kwargs):
    if created:
        tasks.track.delay(instance.game.owner.pk, 'Create Release',
                          game=instance.game.slug,
                          distinct_id=instance.game.owner.username)


def asset_path(asset, filename):
    return os.path.join(asset.release.game.uuid,
                        asset.release.version, filename)


class Asset(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    release = models.ForeignKey(Release)
    blob = models.FileField(upload_to=asset_path, max_length=200)
    tag = models.CharField(max_length=20)

    def appcast(self):
        return {
            'url': self.blob.url.replace("https://", "http://"),
            'length': self.blob.size,
        }

    def __unicode__(self):
        return self.blob.name


class CrashReport(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    game = models.ForeignKey(Game)
    traceback = models.TextField()
    # Eventually switch to hstore
    distinct_id = models.CharField(max_length=24, default='')
    version = models.CharField(max_length=14, default='')
    os = models.CharField(max_length=14, default='')
    uuid = models.CharField(max_length=24, db_index=True, unique=True)

    def save(self, *args, **kwargs):
        if not self.uuid:
            self.uuid = tubeid()
        super(CrashReport, self).save(*args, **kwargs)
