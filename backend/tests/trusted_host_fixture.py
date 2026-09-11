from sumika_core.host_authorization import CallerContext, confirmation_digest


def trusted_rpc(application, method, params):
    caller = CallerContext(method, confirmation_digest(method, params), application.host_authorization._issuer)
    return application.rpc(method, params, caller=caller)
