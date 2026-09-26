"""Errors raised by the wFirma client."""


class WfirmaError(Exception):
    """Base class for wFirma errors."""


class WfirmaAuthError(WfirmaError):
    """The keys were rejected: the user must re-enter them."""


class WfirmaRateLimitError(WfirmaError):
    """wFirma asked us to slow down. Temporary; never a reason to ask for new keys."""


class WfirmaConnectionError(WfirmaError):
    """wFirma could not be reached or answered with an HTTP error."""


class WfirmaResponseError(WfirmaError):
    """wFirma answered, but not with something usable."""


class WfirmaNotFoundError(WfirmaResponseError):
    """The requested record does not exist."""
