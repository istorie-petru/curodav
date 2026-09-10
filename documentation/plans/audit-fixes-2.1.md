# Urgent To do List

The banner upload modal window doesn't work. The image crop/rotate, on external mouse click always exists, even if the user is trying to crop the image (remove the if click outside then exit for it).
When inline changing labels in Tasks page, the pills revert to a blue no icon pill, even if they normally have color and icon. A refresh fixes this. It shoudn't need a refresh.
In the Planner page, tasks with 0 work sessions should not appear in the unnscheduled work card. I would also like to remove the minus and plus for these pills and allow for the task title to show a bit more, a bit of space and then at the end the number of session needed to alocate. The minus and plus alocation system will be replaced by the already in place - drag and drop the task (if it has a work session assigned),click on it, add one more unscheduled session from the same page, drag and drop the other one wherever the user wants.
The kanban board for tasks doesn't allow for tasks to be drag and dropped. 
In the projects page, I would like the agenda card to also include tasks due date in that list, like other widgets in the normal dashboard.
In the unscheduled work, for any pill inside it, the user could click it and open the task view modal window.
Contacts edit modal window doesn't use the custom drop down menus
The Kanbar board columns should try to not add a horizonntal scrollbar. It should first try to have them all in one row, then two rows, and only last the 4 rows for the 4 columns. Keep in mind to calculate depending on the sidebar width.

In the settings, in the Data & Maintenence, the Purge Completed Tasks should sit in the context mennu of Database (as purge completed). The reset home layout button should be removed, because in edit mode an exact button already exists.

I would like to move the password, username, radicale url etc, settings from general to a new page named Your Profile. It should include the Profile Picture and Nickname (current Your Name, used in greeting). 
The Restart app should also be moved to the Data & Maintenance and should be able to be called after editing important enviroment data for the app, appearing in the form of a toast.

For the settings, the page-header-narrow-back, it should be on the left most, not right most.

While adding a hollday, in the specific modal window, after setting either the start and end date, the other one should be automatically set the same. After the initial set both can be changed without any sync between them. This is only to make one day hollyday easier to add.

Hollydays should add support for only day hollydays, withot the year. For example religious national holydays that are the same each time each year.

Holiday bug, for some reason the user is not allowed to add more holidays to the same calendar, and it defaults to Default calendar.

Holiday table, the Date Range for one date holidays should only be one day, not a range.

For the table type of the app (used for tasks and in the app settings) the bulk-actions-bar should only contain two buttons - Delete and Clear - and the bulk-actions-bar buttons should not be placed in the bulk-actions-bar, but in the page-header-narrow. Asure the height doesn't get bigger due to the buttons.

# First round of logs

These are the logs of the first run instance that used the app like intended, and in real life scenarious.

```journalctl -u curodav

Sep 09 10:20:31 curodav systemd[1]: Started curodav.service - Command Center Web (curodav) -- personal organizer PWA.
Sep 09 10:20:34 curodav python[11613]: INFO:     Started server process [11613]
Sep 09 10:20:34 curodav python[11613]: INFO:     Waiting for application startup.
Sep 09 10:20:35 curodav python[11613]: ERROR:src.main:Radicale unreachable at startup; running without the sync bridge
Sep 09 10:20:35 curodav python[11613]: Traceback (most recent call last):
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/connection.py", line 224, in _new_conn
Sep 09 10:20:35 curodav python[11613]:     sock = self._resolver.create_connection(
Sep 09 10:20:35 curodav python[11613]:         (self._dns_host, self.port or self.default_port),
Sep 09 10:20:35 curodav python[11613]:     ...<8 lines>...
Sep 09 10:20:35 curodav python[11613]:         default_socket_family=self._socket_family,
Sep 09 10:20:35 curodav python[11613]:     )
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/contrib/resolver/protocols.py", line 321, in create_connection
Sep 09 10:20:35 curodav python[11613]:     raise err
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/contrib/resolver/protocols.py", line 288, in create_connection
Sep 09 10:20:35 curodav python[11613]:     sock.connect(sa)
Sep 09 10:20:35 curodav python[11613]:     ~~~~~~~~~~~~^^^^
Sep 09 10:20:35 curodav python[11613]: ConnectionRefusedError: [Errno 111] Connection refused
Sep 09 10:20:35 curodav python[11613]: The above exception was the direct cause of the following exception:
Sep 09 10:20:35 curodav python[11613]: Traceback (most recent call last):
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/connectionpool.py", line 1826, in urlopen
Sep 09 10:20:35 curodav python[11613]:     response = self._make_request(  # type: ignore[call-overload,misc]
Sep 09 10:20:35 curodav python[11613]:         conn,
Sep 09 10:20:35 curodav python[11613]:     ...<15 lines>...
Sep 09 10:20:35 curodav python[11613]:         extension=extension,
Sep 09 10:20:35 curodav python[11613]:     )
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/connectionpool.py", line 1310, in _make_request
Sep 09 10:20:35 curodav python[11613]:     raise new_e
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/connectionpool.py", line 1286, in _make_request
Sep 09 10:20:35 curodav python[11613]:     self._validate_conn(conn)
Sep 09 10:20:35 curodav python[11613]:     ~~~~~~~~~~~~~~~~~~~^^^^^^
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/connectionpool.py", line 825, in _validate_conn
Sep 09 10:20:35 curodav python[11613]:     conn.connect()
Sep 09 10:20:35 curodav python[11613]:     ~~~~~~~~~~~~^^
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/connection.py", line 276, in connect
Sep 09 10:20:35 curodav python[11613]:     self.sock = self._new_conn()
Sep 09 10:20:35 curodav python[11613]:                 ~~~~~~~~~~~~~~^^
Sep 09 10:20:35 curodav python[11613]:   File "/srv/curodav/current/.venv/lib/python3.14/site-packages/urllib3/connection.py", line 244, in _new_conn
Sep 09 10:20:35 curodav python[11613]:     raise NewConnectionError(
Sep 09 10:20:35 curodav python[11613]:         self, f"Failed to establish a new connection: {e}"
Sep 09 10:20:35 curodav python[11613]:     ) from e
Sep 09 10:20:35 curodav python[11613]: urllib3.exceptions.NewConnectionError: <urllib3.connection.HTTPConnection object at 0x7165a41ad010>: Failed to establish a new connection: [Errno 111] Connectio>
Sep 09 10:20:35 curodav python[11613]: The above exception was the direct cause of the following exception:

```

# Second round of logs

```

INFO:     127.0.0.1:54326 - "POST /export/import/auto HTTP/1.1" 500 Internal Server Error
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/vobject/base.py", line 533, in __getattr__
    return self.contents[toVName(name)][0]
           ~~~~~~~~~~~~~^^^^^^^^^^^^^^^
KeyError: 'uid'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/uvicorn/protocols/http/httptools_impl.py", line 422, in run_asgi
    result = await app(  # type: ignore[func-returns-value]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        self.scope, self.receive, self.send
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/uvicorn/middleware/proxy_headers.py", line 63, in __call__
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/applications.py", line 1163, in __call__
    await super().__call__(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/applications.py", line 107, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/middleware/errors.py", line 186, in __call__
    raise exc
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/middleware/errors.py", line 164, in __call__
    await self.app(scope, receive, _send)
  File "/home/peter/Claude/Projects/Dashboard/webapp/src/security_headers.py", line 120, in __call__
    return await self.app(scope, receive, send_wrapper)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/webapp/src/auth.py", line 485, in __call__
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/webapp/src/auth.py", line 721, in __call__
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/middleware/gzip.py", line 29, in __call__
    await responder(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/middleware/gzip.py", line 130, in __call__
    await super().__call__(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/middleware/gzip.py", line 46, in __call__
    await self.app(scope, receive, self.send_with_compression)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/middleware/exceptions.py", line 63, in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/middleware/asyncexitstack.py", line 18, in __call__
    await self.app(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/routing.py", line 716, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 2734, in app
    await route.handle(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 1780, in handle
    await self.original_router.handle(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 2789, in handle
    await included_router._handle_selected(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 1800, in _handle_selected
    await original_route.handle(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 1279, in handle
    await app(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 158, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 144, in app
    response = await f(request)
               ^^^^^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 706, in app
    raw_response = await run_endpoint_function(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 354, in run_endpoint_function
    return await run_in_threadpool(dependant.call, **values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/starlette/concurrency.py", line 32, in run_in_threadpool
    return await anyio.to_thread.run_sync(func)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/anyio/to_thread.py", line 65, in run_sync
    return await get_async_backend().run_sync_in_worker_thread(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        func, args, abandon_on_cancel=abandon_on_cancel, limiter=limiter
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 2641, in run_sync_in_worker_thread
    return await future
           ^^^^^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 1033, in run
    result = context.run(func, *args)
  File "/home/peter/Claude/Projects/Dashboard/webapp/src/routers/export.py", line 640, in import_auto
    added = _import_vcf_text(conn, text, skip_existing=skip_existing)
  File "/home/peter/Claude/Projects/Dashboard/webapp/src/routers/export.py", line 424, in _import_vcf_text
    row = vcard_rows.vcard_to_contact_row(card)
  File "/home/peter/Claude/Projects/Dashboard/webapp/src/vcard_rows.py", line 219, in vcard_to_contact_row
    row: dict[str, Any] = {"uid": str(card.uid.value)}
                                      ^^^^^^^^
  File "/home/peter/Claude/Projects/Dashboard/.venv/lib/python3.14/site-packages/vobject/base.py", line 535, in __getattr__
    raise AttributeError(name)
AttributeError: uid

```

The format of it:

```

BEGIN:VCARD
VERSION:3.0
FN:Administrator
N:Administrator;;;;
PHOTO;ENCODING=b;TYPE=image/png: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
PRODID:-//Sabre//Sabre VObject 4.5.6//EN
X-SOCIALPROFILE-SOCIALPROFILE:https://cloud.uccs.ro/index.php/u/administrat
 or

```