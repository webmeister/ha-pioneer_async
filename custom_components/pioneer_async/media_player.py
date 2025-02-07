"""Pioneer AVR media_player platform."""

from __future__ import annotations

import logging
import json
from typing import Any

import voluptuous as vol

from aiopioneer import PioneerAVR
from aiopioneer.const import SOURCE_TUNER, Zones, TunerBand
from aiopioneer.param import PARAM_DISABLE_AUTO_QUERY, PARAM_VOLUME_STEP_ONLY

from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import PlatformNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CLASS_PIONEER,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_PANEL_LOCK,
    SERVICE_SET_REMOTE_LOCK,
    SERVICE_SET_DIMMER,
    SERVICE_SET_TONE_SETTINGS,
    # SERVICE_SET_AMP_SETTINGS,
    SERVICE_SELECT_TUNER_BAND,
    SERVICE_SET_FM_TUNER_FREQUENCY,
    SERVICE_SET_AM_TUNER_FREQUENCY,
    SERVICE_SELECT_TUNER_PRESET,
    SERVICE_SET_CHANNEL_LEVELS,
    # SERVICE_SET_VIDEO_SETTINGS,
    # SERVICE_SET_DSP_SETTINGS,
    ATTR_PIONEER,
    ATTR_COORDINATORS,
    ATTR_DEVICE_INFO,
    ATTR_OPTIONS,
    ATTR_COMMAND,
    ATTR_PREFIX,
    ATTR_SUFFIX,
    ATTR_PANEL_LOCK,
    ATTR_REMOTE_LOCK,
    ATTR_DIMMER,
    ATTR_TONE,
    ATTR_TREBLE,
    ATTR_BASS,
    ATTR_BAND,
    ATTR_FREQUENCY,
    ATTR_CLASS,
    ATTR_PRESET,
    ATTR_CHANNEL,
    ATTR_LEVEL,
)
from .coordinator import PioneerAVRZoneCoordinator
from .debug import Debug
from .entity_base import PioneerEntityBase

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

PARAM_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)

PIONEER_SEND_COMMAND_SCHEMA = {
    vol.Required(ATTR_COMMAND): cv.string,
    vol.Optional(ATTR_PREFIX): cv.string,
    vol.Optional(ATTR_SUFFIX): cv.string,
}

PIONEER_SET_PANEL_LOCK_SCHEMA = {
    vol.Required(ATTR_PANEL_LOCK): cv.string,
}

PIONEER_SET_REMOTE_LOCK_SCHEMA = {
    vol.Required(ATTR_REMOTE_LOCK): cv.boolean,
}

PIONEER_SERVICE_SET_DIMMER_SCHEMA = {
    vol.Required(ATTR_DIMMER): cv.string,
}

PIONEER_SET_TONE_SETTINGS_SCHEMA = {
    vol.Required(ATTR_TONE): cv.string,
    vol.Required(ATTR_TREBLE): vol.All(vol.Coerce(int), vol.Range(min=-6, max=6)),
    vol.Required(ATTR_BASS): vol.All(vol.Coerce(int), vol.Range(min=-6, max=6)),
}

# PIONEER_SET_AMP_SETTINGS_SCHEMA = {
# }

PIONEER_SELECT_TUNER_BAND_SCHEMA = {
    vol.Required(ATTR_BAND): str,
}


PIONEER_SET_FM_TUNER_FREQUENCY_SCHEMA = {
    vol.Required(ATTR_FREQUENCY): vol.All(
        vol.Coerce(float), vol.Range(min=87.5, max=108)
    ),
}

PIONEER_SET_AM_TUNER_FREQUENCY_SCHEMA = {
    vol.Required(ATTR_FREQUENCY): vol.All(
        vol.Coerce(int), vol.Range(min=530, max=1700)
    ),
}

PIONEER_SELECT_TUNER_PRESET_SCHEMA = {
    vol.Required(ATTR_CLASS): cv.string,
    vol.Required(ATTR_PRESET): vol.All(vol.Coerce(int), vol.Range(min=1, max=9)),
}

PIONEER_SET_CHANNEL_LEVELS_SCHEMA = {
    vol.Required(ATTR_CHANNEL): cv.string,
    vol.Required(ATTR_LEVEL): vol.All(vol.Coerce(float), vol.Range(min=-12, max=12)),
}

# PIONEER_SET_VIDEO_SETTINGS_SCHEMA = {
# }

# PIONEER_SET_DSP_SETTINGS_SCHEMA = {
# }


## Debug levels:
##  1: service calls
##  7: callback calls
##  8: update options flow
##  9: component load/unload
def _debug_atlevel(level: int, category: str = __name__):
    return Debug.atlevel(None, level, category)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media_player platform."""
    pioneer_data = hass.data[DOMAIN][config_entry.entry_id]
    pioneer: PioneerAVR = pioneer_data[ATTR_PIONEER]
    options: dict[str, Any] = pioneer_data[ATTR_OPTIONS]
    coordinators: list[PioneerAVRZoneCoordinator] = pioneer_data[ATTR_COORDINATORS]
    zone_device_info = pioneer_data[ATTR_DEVICE_INFO]
    if _debug_atlevel(9):
        _LOGGER.debug(
            ">> media_player.async_setup_entry(entry_id=%s, data=%s, options=%s)",
            config_entry.entry_id,
            config_entry.data,
            options,
        )

    if Zones.Z1 not in pioneer.zones:
        _LOGGER.error("Main zone not found on AVR")
        raise PlatformNotReady  # pylint: disable=raise-missing-from

    ## Add zone specific media_players
    entities = []
    _LOGGER.info("Adding entities for zones %s", pioneer.zones)
    for zone in pioneer.zones:
        entities.append(
            PioneerZone(
                pioneer,
                options,
                coordinator=coordinators[zone],
                device_info=zone_device_info[zone],
                zone=zone,
            )
        )
        _LOGGER.debug("Created entity for zone %s", zone)

    try:
        await pioneer.update()
    except Exception as exc:  # pylint: disable=broad-except
        _LOGGER.error(
            "Could not perform AVR initial update: %s: %s",
            type(exc).__name__,
            str(exc),
        )
        raise PlatformNotReady  # pylint: disable=raise-missing-from

    async_add_entities(entities)

    ## Register platform specific services
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_SEND_COMMAND,
        PIONEER_SEND_COMMAND_SCHEMA,
        PioneerZone.async_send_command,
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        SERVICE_SET_PANEL_LOCK, PIONEER_SET_PANEL_LOCK_SCHEMA, "async_set_panel_lock"
    )
    platform.async_register_entity_service(
        SERVICE_SET_REMOTE_LOCK, PIONEER_SET_REMOTE_LOCK_SCHEMA, "async_set_remote_lock"
    )
    platform.async_register_entity_service(
        SERVICE_SET_DIMMER, PIONEER_SERVICE_SET_DIMMER_SCHEMA, "async_set_dimmer"
    )
    platform.async_register_entity_service(
        SERVICE_SET_TONE_SETTINGS,
        PIONEER_SET_TONE_SETTINGS_SCHEMA,
        "async_set_tone_settings",
    )
    # platform.async_register_entity_service(
    #     SERVICE_SET_AMP_SETTINGS, PIONEER_SET_AMP_SETTINGS_SCHEMA, "async_set_amp_settings"
    # )

    platform.async_register_entity_service(
        SERVICE_SELECT_TUNER_BAND,
        PIONEER_SELECT_TUNER_BAND_SCHEMA,
        "async_select_tuner_band",
    )
    platform.async_register_entity_service(
        SERVICE_SET_FM_TUNER_FREQUENCY,
        PIONEER_SET_FM_TUNER_FREQUENCY_SCHEMA,
        "async_set_fm_tuner_frequency",
    )
    platform.async_register_entity_service(
        SERVICE_SET_AM_TUNER_FREQUENCY,
        PIONEER_SET_AM_TUNER_FREQUENCY_SCHEMA,
        "async_set_am_tuner_frequency",
    )
    platform.async_register_entity_service(
        SERVICE_SELECT_TUNER_PRESET,
        PIONEER_SELECT_TUNER_PRESET_SCHEMA,
        "async_select_tuner_preset",
    )
    platform.async_register_entity_service(
        SERVICE_SET_CHANNEL_LEVELS,
        PIONEER_SET_CHANNEL_LEVELS_SCHEMA,
        "async_set_channel_levels",
    )
    # platform.async_register_entity_service(
    #     SERVICE_SET_VIDEO_SETTINGS, PIONEER_SET_VIDEO_SETTINGS_SCHEMA, "async_set_video_settings"
    # )
    # platform.async_register_entity_service(
    #     SERVICE_SET_DSP_SETTINGS, PIONEER_SET_DSP_SETTINGS_SCHEMA, "async_set_dsp_settings"
    # )


class PioneerZone(
    PioneerEntityBase, MediaPlayerEntity, CoordinatorEntity
):  # pylint: disable=abstract-method
    """Pioneer media_player class."""

    _attr_device_class = CLASS_PIONEER
    _attr_name = None

    def __init__(
        self,
        pioneer: PioneerAVR,
        options: dict[str, Any],
        coordinator: PioneerAVRZoneCoordinator,
        device_info: DeviceInfo,
        zone: Zones,
    ) -> None:
        """Initialize the Pioneer media_player class."""
        if _debug_atlevel(9):
            _LOGGER.debug("PioneerZone.__init__(%s)", zone)
        super().__init__(pioneer, options, device_info=device_info, zone=zone)
        CoordinatorEntity.__init__(self, coordinator)

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the zone."""
        state = self.pioneer.power.get(self.zone)
        if state is None:
            return STATE_UNKNOWN
        return MediaPlayerState.ON if state else MediaPlayerState.OFF

    @property
    def available(self) -> bool:
        """Returns whether the AVR is available. Available even when zone is off."""
        return self.pioneer.available

    @property
    def volume_level(self) -> float:
        """Volume level of the media player (0..1)."""
        volume = self.pioneer.volume.get(self.zone)
        max_volume = self.pioneer.max_volume.get(self.zone)
        return volume / max_volume if (volume and max_volume) else float(0)

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        return self.pioneer.mute.get(self.zone, False)

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        ## Automatically detect what features are supported by what parameters are available
        features = MediaPlayerEntityFeature(0)
        pioneer = self.pioneer
        if pioneer.power.get(self.zone) is not None:
            features |= MediaPlayerEntityFeature.TURN_ON
            features |= MediaPlayerEntityFeature.TURN_OFF
        if pioneer.volume.get(self.zone) is not None:
            features |= MediaPlayerEntityFeature.VOLUME_SET
            features |= MediaPlayerEntityFeature.VOLUME_STEP
        if pioneer.mute.get(self.zone) is not None:
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        if pioneer.source.get(self.zone) is not None:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE

        ## Sound mode is only available on main zone, also it does not return an
        ## output if the AVR is off so add this manually until we figure out a better way
        ## Disable sound mode also if autoquery is disabled
        if self.zone == Zones.Z1 and not pioneer.get_params().get(
            PARAM_DISABLE_AUTO_QUERY
        ):
            features |= MediaPlayerEntityFeature.SELECT_SOUND_MODE

        ## Enable prev/next track if tuner enabled
        if pioneer.source.get(self.zone) == SOURCE_TUNER:
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
            features |= MediaPlayerEntityFeature.NEXT_TRACK

        return features

    @property
    def sound_mode(self) -> str | None:
        """Return the current sound mode."""
        ## Sound modes only supported on zones with speakers, return null if nothing found
        return self.pioneer.listening_mode

    @property
    def sound_mode_list(self) -> list[str]:
        """Returns all valid sound modes from aiopioneer."""
        if self.zone != Zones.Z1:
            return None

        listening_modes = self.pioneer.get_listening_modes()
        return (
            [v for _, v in sorted(listening_modes.items())] if listening_modes else None
        )

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        source_id = self.pioneer.source.get(self.zone)
        if source_id:
            return self.pioneer.get_source_name(source_id)
        else:
            return None

    @property
    def source_list(self) -> list[str]:
        """List of available input sources."""
        return self.pioneer.get_source_list(self.zone)

    @property
    def media_title(self) -> str:
        """Title of current playing media."""
        return self.source

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device specific state attributes."""
        pioneer = self.pioneer
        attrs = {"sources_json": json.dumps(pioneer.get_source_dict(self.zone))}

        ## Return max volume attributes
        volume = pioneer.volume.get(self.zone)
        max_volume = pioneer.max_volume.get(self.zone)
        if volume is not None and max_volume is not None:
            if self.zone == Zones.Z1:
                volume_db = volume / 2 - 80.5
            else:
                volume_db = volume - 81
            attrs |= {
                "device_volume": volume,
                "device_max_volume": max_volume,
                "device_volume_db": volume_db,
            }
        return attrs

    async def async_update(self) -> None:
        """Poll properties on demand."""
        if _debug_atlevel(8):
            _LOGGER.debug(">> PioneerZone.async_update(%s)", self.zone)
        return await self.pioneer.update()

    async def async_turn_on(self) -> None:
        """Turn the media player on."""

        async def turn_on() -> None:
            await self.pioneer.turn_on(zone=self.zone)

        await self.pioneer_command(turn_on, repeat=True)

    async def async_turn_off(self) -> None:
        """Turn off media player."""

        async def turn_off() -> None:
            await self.pioneer.turn_off(zone=self.zone)

        await self.pioneer_command(turn_off, repeat=True)

    async def async_select_source(self, source: str) -> None:
        """Select input source."""

        async def select_source() -> None:
            await self.pioneer.select_source(source, zone=self.zone)

        await self.pioneer_command(select_source, repeat=True)

    async def async_volume_up(self) -> None:
        """Volume up media player."""

        async def volume_up() -> None:
            await self.pioneer.volume_up(zone=self.zone)

        await self.pioneer_command(volume_up)

    async def async_volume_down(self) -> None:
        """Volume down media player."""

        async def volume_down() -> None:
            await self.pioneer.volume_down(zone=self.zone)

        await self.pioneer_command(volume_down)

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""

        async def tuner_previous_preset() -> None:
            await self.pioneer.tuner_previous_preset()

        await self.pioneer_command(tuner_previous_preset)

    async def async_media_next_track(self) -> None:
        """Send next track command."""

        async def tuner_next_preset() -> None:
            return await self.pioneer.tuner_next_preset()

        await self.pioneer_command(tuner_next_preset)

    async def async_set_volume_level(self, volume) -> None:
        """Set volume level, range 0..1."""
        max_volume = self.pioneer.max_volume.get(self.zone)

        async def set_volume_level() -> None:
            await self.pioneer.set_volume_level(
                round(volume * max_volume), zone=self.zone
            )

        if self.pioneer.get_params().get(PARAM_VOLUME_STEP_ONLY):
            await self.pioneer_command(set_volume_level)
        else:
            await self.pioneer_command(set_volume_level, repeat=True)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute (true) or unmute (false) media player."""

        async def mute_volume() -> None:
            if mute:
                await self.pioneer.mute_on(zone=self.zone)
            else:
                await self.pioneer.mute_off(zone=self.zone)

        await self.pioneer_command(mute_volume, repeat=True)

    async def async_select_sound_mode(self, sound_mode) -> None:
        """Select the sound mode."""

        async def select_sound_mode() -> None:
            ## aiopioneer will translate sound modes
            await self.pioneer.select_listening_mode(sound_mode)

        await self.pioneer_command(select_sound_mode, repeat=True)

    async def async_send_command(self, service_call: ServiceCall) -> ServiceResponse:
        """Send command to the AVR."""
        command = service_call.data[ATTR_COMMAND]
        prefix = service_call.data.get(ATTR_PREFIX, "")
        suffix = service_call.data.get(ATTR_SUFFIX, "")
        _LOGGER.info(
            ">> send_command(%s, command=%s, prefix=%s, suffix=%s)",
            self.zone,
            command,
            prefix,
            suffix,
        )

        async def send_command():
            return await self.pioneer.send_command(
                command, zone=self.zone, prefix=prefix, suffix=suffix
            )

        resp = await self.pioneer_command(send_command, command=command)
        if service_call.return_response:
            return resp

    async def async_set_panel_lock(self, panel_lock: str) -> None:
        """Set AVR panel lock."""
        if _debug_atlevel(1):
            _LOGGER.debug(">> PioneerZone.set_panel_lock(panel_lock=%s)", panel_lock)

        async def set_panel_lock() -> None:
            await self.pioneer.set_panel_lock(panel_lock)

        await self.pioneer_command(set_panel_lock)

    async def async_set_remote_lock(self, remote_lock: bool) -> None:
        """Set AVR remote lock."""
        if _debug_atlevel(1):
            _LOGGER.debug(">> PioneerZone.set_remote_lock(remote_lock=%s)", remote_lock)

        async def set_remote_lock() -> None:
            await self.pioneer.set_remote_lock(remote_lock)

        await self.pioneer_command(set_remote_lock)

    async def async_set_dimmer(self, dimmer: str) -> None:
        """Set AVR display dimmer."""
        if _debug_atlevel(1):
            _LOGGER.debug(">> PioneerZone.set_dimmer(dimmer=%s)", dimmer)

        async def set_dimmer() -> None:
            await self.pioneer.set_dimmer(dimmer)

        await self.pioneer_command(set_dimmer)

    async def async_set_tone_settings(self, tone: str, treble: int, bass: int) -> None:
        """Set AVR tone settings for zone."""
        if _debug_atlevel(1):
            _LOGGER.debug(
                ">> PioneerZone.set_tone_settings(%s, tone=%s, treble=%d, bass=%d)",
                self.zone,
                tone,
                treble,
                bass,
            )

        async def set_tone_settings() -> None:
            await self.pioneer.set_tone_settings(tone, treble, bass, zone=self.zone)

        await self.pioneer_command(set_tone_settings, repeat=True)

    async def async_select_tuner_band(self, band: str) -> None:
        """Set AVR tuner band."""
        if _debug_atlevel(1):
            _LOGGER.debug(
                ">> PioneerZone.select_tuner_band(band=%s)",
                band,
            )

        async def select_tuner_band() -> None:
            await self.pioneer.select_tuner_band(TunerBand(band))

        await self.pioneer_command(select_tuner_band, repeat=True)

    async def async_set_fm_tuner_frequency(self, frequency: float) -> None:
        """Set AVR AM tuner frequency."""
        if _debug_atlevel(1):
            _LOGGER.debug(
                ">> PioneerZone.set_fm_tuner_frequency(frequency=%f)",
                frequency,
            )

        async def set_fm_tuner_frequency() -> None:
            await self.pioneer.set_tuner_frequency(TunerBand.FM, frequency)

        await self.pioneer_command(set_fm_tuner_frequency, repeat=True)

    async def async_set_am_tuner_frequency(self, frequency: int) -> None:
        """Set AVR AM tuner frequency."""
        if _debug_atlevel(1):
            _LOGGER.debug(
                ">> PioneerZone.set_am_tuner_frequency(frequency=%d)",
                frequency,
            )

        async def set_am_tuner_frequency() -> None:
            await self.pioneer.set_tuner_frequency(TunerBand.AM, float(frequency))

        await self.pioneer_command(set_am_tuner_frequency, repeat=True)

    async def async_select_tuner_preset(self, **kwargs) -> None:
        """Set AVR tuner preset."""
        tuner_class = kwargs[ATTR_CLASS]  ## workaround for "class" as argument
        preset = kwargs[ATTR_PRESET]
        if _debug_atlevel(1):
            _LOGGER.debug(
                ">> PioneerZone.select_tuner_preset(class=%s, preset=%d)",
                tuner_class,
                preset,
            )

        async def select_tuner_preset() -> None:
            await self.pioneer.select_tuner_preset(tuner_class, preset)

        await self.pioneer_command(select_tuner_preset, repeat=True)

    async def async_set_channel_levels(self, channel: str, level: float) -> None:
        """Set AVR level (gain) for amplifier channel in zone."""
        if _debug_atlevel(1):
            _LOGGER.debug(
                ">> PioneerZone.set_channel_levels(%s, channel=%s, level=%f)",
                self.zone,
                channel,
                level,
            )

        async def set_channel_levels() -> None:
            await self.pioneer.set_channel_levels(channel, level, zone=self.zone)

        await self.pioneer_command(set_channel_levels, repeat=True)
