---
name: Bug report
about: Something behaves differently than documented
labels: bug
---

**What happened**

<!-- Include the traceback if there is one. -->

**What you expected**

**Reproduction**

```python
import asyncio
import aiopynautobot


async def main():
    async with aiopynautobot.api("https://nautobot.example.com", token="...") as nb:
        ...


asyncio.run(main())
```

**Versions**

- aiopynautobot:
- Nautobot:
- Python:

**Anything else**

<!-- Does pynautobot behave differently here? That is useful to know. -->
