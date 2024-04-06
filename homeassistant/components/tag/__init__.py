"""The Tag integration."""

from __future__ import annotations

import logging
import uuid

import voluptuous as vol

from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import collection, discovery
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
import homeassistant.util.dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import DEVICE_ID, DOMAIN, EVENT_TAG_SCANNED, TAG_ID

_LOGGER = logging.getLogger(__name__)

LAST_SCANNED = "last_scanned"
STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

TAG_DATA: HassKey[TagStorageCollection] = HassKey(DOMAIN)
TAGS_ENTITIES = "tags_entities"

CREATE_FIELDS = {
    vol.Optional(TAG_ID): cv.string,
    vol.Optional(CONF_NAME): vol.All(str, vol.Length(min=1)),
    vol.Optional("description"): cv.string,
    vol.Optional(LAST_SCANNED): cv.datetime,
    vol.Optional(DEVICE_ID): cv.string,
}

UPDATE_FIELDS = {
    vol.Optional(CONF_NAME): vol.All(str, vol.Length(min=1)),
    vol.Optional("description"): cv.string,
    vol.Optional(LAST_SCANNED): cv.datetime,
    vol.Optional(DEVICE_ID): cv.string,
}

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


class TagIDExistsError(HomeAssistantError):
    """Raised when an item is not found."""

    def __init__(self, item_id: str) -> None:
        """Initialize tag ID exists error."""
        super().__init__(f"Tag with ID {item_id} already exists.")
        self.item_id = item_id


class TagIDManager(collection.IDManager):
    """ID manager for tags."""

    def generate_id(self, suggestion: str) -> str:
        """Generate an ID."""
        if self.has_id(suggestion):
            raise TagIDExistsError(suggestion)

        return suggestion


class TagStorageCollection(collection.DictStorageCollection):
    """Tag collection stored in storage."""

    CREATE_SCHEMA = vol.Schema(CREATE_FIELDS)
    UPDATE_SCHEMA = vol.Schema(UPDATE_FIELDS)

    async def _process_create_data(self, data: dict) -> dict:
        """Validate the config is valid."""
        data = self.CREATE_SCHEMA(data)
        if not data[TAG_ID]:
            data[TAG_ID] = str(uuid.uuid4())
        # make last_scanned JSON serializeable
        if LAST_SCANNED in data:
            data[LAST_SCANNED] = data[LAST_SCANNED].isoformat()
        return data

    @callback
    def _get_suggested_id(self, info: dict[str, str]) -> str:
        """Suggest an ID based on the config."""
        return info[TAG_ID]

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        """Return a new updated data object."""
        data = {**item, **self.UPDATE_SCHEMA(update_data)}
        # make last_scanned JSON serializeable
        if LAST_SCANNED in update_data:
            data[LAST_SCANNED] = data[LAST_SCANNED].isoformat()
        return data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Tag component."""
    id_manager = TagIDManager()
    hass.data[TAG_DATA] = storage_collection = TagStorageCollection(
        Store(hass, STORAGE_VERSION, STORAGE_KEY),
        id_manager,
    )
    await storage_collection.async_load()
    collection.DictStorageCollectionWebsocket(
        storage_collection, DOMAIN, DOMAIN, CREATE_FIELDS, UPDATE_FIELDS
    ).async_setup(hass)

    await hass.async_create_task(
        discovery.async_load_platform(
            hass,
            Platform.EVENT,
            DOMAIN,
            {},
            config,
        )
    )

    return True


async def async_scan_tag(
    hass: HomeAssistant,
    tag_id: str,
    device_id: str | None,
    context: Context | None = None,
) -> None:
    """Handle when a tag is scanned."""
    if DOMAIN not in hass.config.components:
        raise HomeAssistantError("tag component has not been set up.")

    storage_collection = hass.data[TAG_DATA]

    # Get name from helper, default value None if not present in data
    tag_name = None
    if tag_data := storage_collection.data.get(tag_id):
        tag_name = tag_data.get(CONF_NAME)

    hass.bus.async_fire(
        EVENT_TAG_SCANNED,
        {TAG_ID: tag_id, CONF_NAME: tag_name, DEVICE_ID: device_id},
        context=context,
    )

    if tag_id in storage_collection.data:
        await storage_collection.async_update_item(
            tag_id, {LAST_SCANNED: dt_util.utcnow(), DEVICE_ID: device_id}
        )
    else:
        await storage_collection.async_create_item(
            {TAG_ID: tag_id, LAST_SCANNED: dt_util.utcnow(), DEVICE_ID: device_id}
        )
    _LOGGER.debug("Tag: %s scanned by device: %s", tag_id, device_id)
