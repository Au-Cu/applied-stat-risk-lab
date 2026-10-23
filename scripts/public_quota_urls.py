"""Public evidence links only; never follow file links or publish login tokens."""
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def public_url(value):
    parts=urlsplit(str(value))
    if parts.scheme.lower() not in ('https','http') or not parts.hostname:
        return ''
    host=parts.hostname.lower()
    if host in ('localhost','localhost.localdomain') or parts.username or parts.password:
        return ''
    try:
        if not ipaddress.ip_address(host).is_global:
            return ''
    except ValueError:
        pass
    pairs=parse_qsl(parts.query,keep_blank_values=True)
    if host=='mp.weixin.qq.com':
        pairs=[(k,v) for k,v in pairs if k in ('__biz','mid','idx','sn')]
        query=urlencode(pairs)
    else:
        secret={'access_token','auth_token','pass_ticket','exportkey','uin','sessionid','session_id'}
        query=urlencode([(k,v) for k,v in pairs if k.lower() not in secret]) if any(k.lower() in secret for k,v in pairs) else parts.query
    return urlunsplit((parts.scheme,parts.netloc,parts.path,query,''))

def public_error(value):
    return re.sub(r'https?://[^\s\x27\x22<>]+',lambda m:public_url(m[0]) or '[non-public link removed]',str(value))
