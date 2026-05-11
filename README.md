# Grimora

Grimora is a fully static discord channel archive written with fastapi and pure html + css.

## Authentication

Grimora now requires HTTP Basic authentication for every route, including transcript pages, search, uploads, and static assets.
Set these environment variables before starting it:

```bash
export GRIMORA_AUTH_USERNAME=your-user
export GRIMORA_AUTH_PASSWORD='a-long-random-password'
```

Optional:

```bash
export GRIMORA_AUTH_REALM=Grimora
```

## Features
- [x] transcript upload
- [x] search
- [ ] transcript/channel one file download


## Todo

- display modified tag
- make replies link to the msg
- properly format audio attachments
- fix fonts
- change code font
- highlighting links
- harden the cache against ssrf
- general web config
- docker integration
    
