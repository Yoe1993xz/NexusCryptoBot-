import staypresent
import os

staypresent.web.json({"status": "running"})

staypresent.run(
    "bot.py",
    port=int(os.getenv("PORT", 8080))
)
