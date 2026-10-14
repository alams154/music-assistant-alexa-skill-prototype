"""Config flow for the Nabu Casa skill bridge."""

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class MusicAssistantAlexaSkillConfigFlow(ConfigFlow, domain=DOMAIN):
    """One config entry that owns the cloud webhook."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_create_entry(title="Music Assistant Alexa Skill", data={})
