"""Blueprints — built-in project templates for generating applications.

Each blueprint describes a project type (web app, Android game, online store, etc.)
with its file structure, code skeletons, dependencies, build commands, and a
system prompt that guides the Ollama model when generating code.

Blueprints are stored as JSON on disk alongside the knowledge base and can be
edited through the admin panel.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BlueprintFile:
    """A single file template within a blueprint."""

    path: str  # relative path, e.g. "src/main.py"
    content: str = ""  # skeleton / boilerplate content
    description: str = ""  # what this file is for
    generate: bool = True  # whether the model should generate/fill this file

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "description": self.description,
            "generate": self.generate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlueprintFile:
        return cls(
            path=data.get("path", ""),
            content=data.get("content", ""),
            description=data.get("description", ""),
            generate=data.get("generate", True),
        )


@dataclass
class Blueprint:
    """A project blueprint — template for generating a full application."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    category: str = ""  # web-app, android, game, store, api, bot, etc.
    description: str = ""
    language: str = ""  # primary language: python, javascript, kotlin, etc.
    framework: str = ""  # flask, fastapi, react, android-sdk, etc.
    files: list[BlueprintFile] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    build_commands: list[str] = field(default_factory=list)
    run_command: str = ""
    system_prompt: str = ""  # guides the model when generating code
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "language": self.language,
            "framework": self.framework,
            "files": [f.to_dict() for f in self.files],
            "dependencies": self.dependencies,
            "build_commands": self.build_commands,
            "run_command": self.run_command,
            "system_prompt": self.system_prompt,
            "tags": self.tags,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Blueprint:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            name=data.get("name", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            language=data.get("language", ""),
            framework=data.get("framework", ""),
            files=[BlueprintFile.from_dict(f) for f in data.get("files", [])],
            dependencies=data.get("dependencies", []),
            build_commands=data.get("build_commands", []),
            run_command=data.get("run_command", ""),
            system_prompt=data.get("system_prompt", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", time.time()),
        )


# ---------------------------------------------------------------------------
# Seed blueprints
# ---------------------------------------------------------------------------

SEED_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "name": "FastAPI Web Application",
        "category": "web-app",
        "description": "Full-stack web application with FastAPI backend, Jinja2 templates, and SQLite database",
        "language": "python",
        "framework": "fastapi",
        "files": [
            {
                "path": "app/main.py",
                "description": "FastAPI application entry point with routes",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/models.py",
                "description": "SQLAlchemy/Pydantic data models",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/database.py",
                "description": "Database connection and session management",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/templates/base.html",
                "description": "Base HTML template with navigation",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/templates/index.html",
                "description": "Home page template",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/static/style.css",
                "description": "Application styles",
                "generate": True,
                "content": "",
            },
            {
                "path": "requirements.txt",
                "description": "Python dependencies",
                "generate": False,
                "content": "fastapi\nuvicorn[standard]\njinja2\nsqlalchemy\naiosqlite\npython-multipart\n",
            },
            {
                "path": "README.md",
                "description": "Project documentation",
                "generate": True,
                "content": "",
            },
        ],
        "dependencies": ["fastapi", "uvicorn", "jinja2", "sqlalchemy", "aiosqlite"],
        "build_commands": ["pip install -r requirements.txt"],
        "run_command": "uvicorn app.main:app --reload",
        "system_prompt": "You are an expert Python web developer. Generate a complete FastAPI web application. Use SQLAlchemy for ORM, Jinja2 for templates, and follow REST best practices. Include proper error handling, input validation with Pydantic, and clean HTML/CSS.",
        "tags": ["python", "web", "fastapi", "fullstack"],
    },
    {
        "name": "Flask Website",
        "category": "website",
        "description": "Multi-page website with Flask, Bootstrap, and SQLite",
        "language": "python",
        "framework": "flask",
        "files": [
            {
                "path": "app.py",
                "description": "Flask application with routes and views",
                "generate": True,
                "content": "",
            },
            {
                "path": "models.py",
                "description": "Database models",
                "generate": True,
                "content": "",
            },
            {
                "path": "templates/base.html",
                "description": "Base template with Bootstrap",
                "generate": True,
                "content": "",
            },
            {
                "path": "templates/index.html",
                "description": "Home page",
                "generate": True,
                "content": "",
            },
            {
                "path": "templates/about.html",
                "description": "About page",
                "generate": True,
                "content": "",
            },
            {
                "path": "static/css/style.css",
                "description": "Custom styles",
                "generate": True,
                "content": "",
            },
            {
                "path": "static/js/main.js",
                "description": "Client-side JavaScript",
                "generate": True,
                "content": "",
            },
            {
                "path": "requirements.txt",
                "description": "Dependencies",
                "generate": False,
                "content": "flask\nflask-sqlalchemy\n",
            },
        ],
        "dependencies": ["flask", "flask-sqlalchemy"],
        "build_commands": ["pip install -r requirements.txt"],
        "run_command": "python app.py",
        "system_prompt": "You are an expert web developer. Generate a complete Flask website with multiple pages. Use Bootstrap 5 for responsive design, Flask-SQLAlchemy for database, and include proper navigation, footer, and clean semantic HTML.",
        "tags": ["python", "web", "flask", "website"],
    },
    {
        "name": "React SPA",
        "category": "web-app",
        "description": "Single-page application with React, React Router, and REST API integration",
        "language": "javascript",
        "framework": "react",
        "files": [
            {
                "path": "src/App.jsx",
                "description": "Root component with routing",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/index.jsx",
                "description": "Entry point",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/components/Header.jsx",
                "description": "Navigation header component",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/components/Footer.jsx",
                "description": "Footer component",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/pages/Home.jsx",
                "description": "Home page component",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/pages/About.jsx",
                "description": "About page component",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/api/client.js",
                "description": "API client for backend communication",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/styles/App.css",
                "description": "Application styles",
                "generate": True,
                "content": "",
            },
            {
                "path": "package.json",
                "description": "Node.js dependencies",
                "generate": False,
                "content": '{"name":"app","version":"1.0.0","private":true,"dependencies":{"react":"^18","react-dom":"^18","react-router-dom":"^6"},"scripts":{"start":"react-scripts start","build":"react-scripts build"}}',
            },
        ],
        "dependencies": ["react", "react-dom", "react-router-dom"],
        "build_commands": ["npm install", "npm run build"],
        "run_command": "npm start",
        "system_prompt": "You are an expert React developer. Generate a complete single-page application with React 18. Use functional components with hooks, React Router for navigation, and clean modular CSS. Follow modern React best practices.",
        "tags": ["javascript", "web", "react", "spa"],
    },
    {
        "name": "Android App (Kotlin)",
        "category": "android",
        "description": "Android application with Kotlin, Jetpack Compose, and MVVM architecture",
        "language": "kotlin",
        "framework": "android-jetpack",
        "files": [
            {
                "path": "app/src/main/java/com/app/MainActivity.kt",
                "description": "Main activity with Compose UI",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/src/main/java/com/app/ui/theme/Theme.kt",
                "description": "Material Design theme",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/src/main/java/com/app/ui/screens/HomeScreen.kt",
                "description": "Home screen composable",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/src/main/java/com/app/viewmodel/MainViewModel.kt",
                "description": "ViewModel with state management",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/src/main/java/com/app/data/Repository.kt",
                "description": "Data repository",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/src/main/AndroidManifest.xml",
                "description": "Android manifest",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/build.gradle.kts",
                "description": "App-level Gradle build file",
                "generate": True,
                "content": "",
            },
            {
                "path": "build.gradle.kts",
                "description": "Project-level Gradle build file",
                "generate": True,
                "content": "",
            },
        ],
        "dependencies": [
            "jetpack-compose",
            "lifecycle-viewmodel",
            "navigation-compose",
        ],
        "build_commands": ["./gradlew assembleDebug"],
        "run_command": "./gradlew installDebug",
        "system_prompt": "You are an expert Android developer. Generate a complete Android application using Kotlin and Jetpack Compose. Use MVVM architecture, Material Design 3, and follow Android best practices. Include proper state management with ViewModel and clean navigation.",
        "tags": ["kotlin", "android", "mobile", "jetpack-compose"],
    },
    {
        "name": "2D Game (Python/Pygame)",
        "category": "game",
        "description": "2D game with Pygame — game loop, sprites, collision detection, and scoring",
        "language": "python",
        "framework": "pygame",
        "files": [
            {
                "path": "main.py",
                "description": "Game entry point and main loop",
                "generate": True,
                "content": "",
            },
            {
                "path": "game/engine.py",
                "description": "Game engine with update/render cycle",
                "generate": True,
                "content": "",
            },
            {
                "path": "game/sprites.py",
                "description": "Player, enemy, and projectile sprites",
                "generate": True,
                "content": "",
            },
            {
                "path": "game/levels.py",
                "description": "Level management and progression",
                "generate": True,
                "content": "",
            },
            {
                "path": "game/ui.py",
                "description": "HUD, menus, and score display",
                "generate": True,
                "content": "",
            },
            {
                "path": "game/assets.py",
                "description": "Asset loading (images, sounds)",
                "generate": True,
                "content": "",
            },
            {
                "path": "requirements.txt",
                "description": "Dependencies",
                "generate": False,
                "content": "pygame\n",
            },
        ],
        "dependencies": ["pygame"],
        "build_commands": ["pip install -r requirements.txt"],
        "run_command": "python main.py",
        "system_prompt": "You are an expert game developer. Generate a complete 2D game using Pygame. Include a proper game loop with delta time, sprite classes with collision detection, a scoring system, multiple levels, and a start/game-over menu. Use clean OOP design.",
        "tags": ["python", "game", "pygame", "2d"],
    },
    {
        "name": "Online Store (E-commerce)",
        "category": "store",
        "description": "E-commerce web application with product catalog, cart, checkout, and admin panel",
        "language": "python",
        "framework": "fastapi",
        "files": [
            {
                "path": "app/main.py",
                "description": "FastAPI app with store routes",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/models.py",
                "description": "Product, Cart, Order models",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/database.py",
                "description": "Database setup",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/auth.py",
                "description": "User authentication and sessions",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/cart.py",
                "description": "Shopping cart logic",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/templates/base.html",
                "description": "Base template with store layout",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/templates/catalog.html",
                "description": "Product catalog page",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/templates/product.html",
                "description": "Single product page",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/templates/cart.html",
                "description": "Shopping cart page",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/templates/checkout.html",
                "description": "Checkout page",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/static/css/store.css",
                "description": "Store styles",
                "generate": True,
                "content": "",
            },
            {
                "path": "requirements.txt",
                "description": "Dependencies",
                "generate": False,
                "content": "fastapi\nuvicorn[standard]\njinja2\nsqlalchemy\naiosqlite\npython-multipart\npython-jose\npasslib[bcrypt]\n",
            },
        ],
        "dependencies": [
            "fastapi",
            "uvicorn",
            "jinja2",
            "sqlalchemy",
            "aiosqlite",
            "python-jose",
            "passlib",
        ],
        "build_commands": ["pip install -r requirements.txt"],
        "run_command": "uvicorn app.main:app --reload",
        "system_prompt": "You are an expert e-commerce developer. Generate a complete online store with product catalog, shopping cart, user authentication, and checkout flow. Use FastAPI with SQLAlchemy, Jinja2 templates, and clean responsive CSS. Include product search, categories, and order management.",
        "tags": ["python", "web", "ecommerce", "store", "fastapi"],
    },
    {
        "name": "REST API Service",
        "category": "api",
        "description": "RESTful API with authentication, CRUD operations, and OpenAPI documentation",
        "language": "python",
        "framework": "fastapi",
        "files": [
            {
                "path": "app/main.py",
                "description": "FastAPI app with API router",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/models.py",
                "description": "SQLAlchemy and Pydantic models",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/database.py",
                "description": "Database connection",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/auth.py",
                "description": "JWT authentication",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/routes/items.py",
                "description": "CRUD routes for items",
                "generate": True,
                "content": "",
            },
            {
                "path": "app/routes/users.py",
                "description": "User management routes",
                "generate": True,
                "content": "",
            },
            {
                "path": "tests/test_api.py",
                "description": "API tests with pytest",
                "generate": True,
                "content": "",
            },
            {
                "path": "requirements.txt",
                "description": "Dependencies",
                "generate": False,
                "content": "fastapi\nuvicorn[standard]\nsqlalchemy\naiosqlite\npython-jose\npasslib[bcrypt]\npytest\nhttpx\n",
            },
        ],
        "dependencies": ["fastapi", "uvicorn", "sqlalchemy", "python-jose", "passlib"],
        "build_commands": ["pip install -r requirements.txt"],
        "run_command": "uvicorn app.main:app --reload",
        "system_prompt": "You are an expert API developer. Generate a complete RESTful API with FastAPI. Include JWT authentication, full CRUD operations, input validation with Pydantic, proper error handling, pagination, and pytest tests. Follow OpenAPI best practices.",
        "tags": ["python", "api", "rest", "fastapi"],
    },
    {
        "name": "Telegram Bot",
        "category": "bot",
        "description": "Telegram bot with command handlers, inline keyboards, and database storage",
        "language": "python",
        "framework": "aiogram",
        "files": [
            {
                "path": "bot/main.py",
                "description": "Bot entry point and dispatcher",
                "generate": True,
                "content": "",
            },
            {
                "path": "bot/handlers.py",
                "description": "Message and command handlers",
                "generate": True,
                "content": "",
            },
            {
                "path": "bot/keyboards.py",
                "description": "Inline and reply keyboards",
                "generate": True,
                "content": "",
            },
            {
                "path": "bot/database.py",
                "description": "SQLite database for user data",
                "generate": True,
                "content": "",
            },
            {
                "path": "bot/config.py",
                "description": "Configuration and environment variables",
                "generate": True,
                "content": "",
            },
            {
                "path": "requirements.txt",
                "description": "Dependencies",
                "generate": False,
                "content": "aiogram>=3.0\naiosqlite\n",
            },
        ],
        "dependencies": ["aiogram", "aiosqlite"],
        "build_commands": ["pip install -r requirements.txt"],
        "run_command": "python -m bot.main",
        "system_prompt": "You are an expert Telegram bot developer. Generate a complete Telegram bot using aiogram 3. Include command handlers (/start, /help), inline keyboards for navigation, user state management with FSM, and SQLite storage for user data. Follow aiogram 3 best practices.",
        "tags": ["python", "bot", "telegram", "aiogram"],
    },
    {
        "name": "CLI Tool",
        "category": "cli",
        "description": "Command-line application with argument parsing, subcommands, and colored output",
        "language": "python",
        "framework": "click",
        "files": [
            {
                "path": "cli/main.py",
                "description": "CLI entry point with Click commands",
                "generate": True,
                "content": "",
            },
            {
                "path": "cli/commands.py",
                "description": "Subcommand implementations",
                "generate": True,
                "content": "",
            },
            {
                "path": "cli/utils.py",
                "description": "Utility functions and helpers",
                "generate": True,
                "content": "",
            },
            {
                "path": "cli/config.py",
                "description": "Configuration file management",
                "generate": True,
                "content": "",
            },
            {
                "path": "setup.py",
                "description": "Package setup with entry points",
                "generate": True,
                "content": "",
            },
            {
                "path": "requirements.txt",
                "description": "Dependencies",
                "generate": False,
                "content": "click\nrich\n",
            },
        ],
        "dependencies": ["click", "rich"],
        "build_commands": ["pip install -e ."],
        "run_command": "python -m cli.main",
        "system_prompt": "You are an expert CLI developer. Generate a complete command-line tool using Click and Rich. Include subcommands, argument/option parsing, colored output with Rich, configuration file support, and proper error handling. Make it user-friendly with help text.",
        "tags": ["python", "cli", "tool", "click"],
    },
    {
        "name": "Node.js Express API",
        "category": "api",
        "description": "REST API with Express.js, MongoDB/SQLite, and JWT authentication",
        "language": "javascript",
        "framework": "express",
        "files": [
            {
                "path": "src/index.js",
                "description": "Express server entry point",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/routes/auth.js",
                "description": "Authentication routes",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/routes/items.js",
                "description": "CRUD routes",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/middleware/auth.js",
                "description": "JWT middleware",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/models/User.js",
                "description": "User model",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/models/Item.js",
                "description": "Item model",
                "generate": True,
                "content": "",
            },
            {
                "path": "src/db.js",
                "description": "Database connection",
                "generate": True,
                "content": "",
            },
            {
                "path": "package.json",
                "description": "Dependencies",
                "generate": False,
                "content": '{"name":"api","version":"1.0.0","main":"src/index.js","scripts":{"start":"node src/index.js","dev":"nodemon src/index.js"},"dependencies":{"express":"^4","better-sqlite3":"^11","jsonwebtoken":"^9","bcryptjs":"^2","cors":"^2"}}',
            },
        ],
        "dependencies": ["express", "better-sqlite3", "jsonwebtoken", "bcryptjs"],
        "build_commands": ["npm install"],
        "run_command": "npm start",
        "system_prompt": "You are an expert Node.js developer. Generate a complete REST API with Express.js. Use better-sqlite3 for database, JWT for authentication, and follow Express best practices. Include proper middleware, error handling, and input validation.",
        "tags": ["javascript", "api", "express", "nodejs"],
    },
]


# ---------------------------------------------------------------------------
# Blueprint store
# ---------------------------------------------------------------------------


class BlueprintStore:
    """Manages blueprint templates on disk."""

    def __init__(self, base_dir: str | Path) -> None:
        self._dir = Path(base_dir) / "blueprints"
        self._dir.mkdir(parents=True, exist_ok=True)

    def seed_if_empty(self) -> int:
        """Populate with built-in blueprints if empty. Returns count seeded."""
        existing = list(self._dir.glob("*.json"))
        if existing:
            return 0
        count = 0
        for bp_data in SEED_BLUEPRINTS:
            bp_id = uuid.uuid4().hex[:12]
            bp_data["id"] = bp_id
            self._write(bp_id, bp_data)
            count += 1
        return count

    def list_blueprints(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all blueprints, optionally filtered by category."""
        results: list[dict[str, Any]] = []
        for path in sorted(self._dir.glob("*.json")):
            data = self._read(path)
            if data is None:
                continue
            if category and data.get("category") != category:
                continue
            # Return summary (without full file contents)
            results.append(
                {
                    "id": data.get("id", ""),
                    "name": data.get("name", ""),
                    "category": data.get("category", ""),
                    "description": data.get("description", ""),
                    "language": data.get("language", ""),
                    "framework": data.get("framework", ""),
                    "tags": data.get("tags", []),
                    "file_count": len(data.get("files", [])),
                }
            )
        return results

    def get(self, bp_id: str) -> Blueprint | None:
        """Load a blueprint by ID."""
        path = self._dir / f"{bp_id}.json"
        if not path.exists():
            return None
        data = self._read(path)
        if data is None:
            return None
        return Blueprint.from_dict(data)

    def save(self, blueprint: Blueprint) -> str:
        """Save or update a blueprint. Returns the ID."""
        self._write(blueprint.id, blueprint.to_dict())
        return blueprint.id

    def delete(self, bp_id: str) -> bool:
        """Delete a blueprint by ID."""
        path = self._dir / f"{bp_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def get_categories(self) -> list[str]:
        """Return all unique categories."""
        cats: set[str] = set()
        for path in self._dir.glob("*.json"):
            data = self._read(path)
            if data and data.get("category"):
                cats.add(data["category"])
        return sorted(cats)

    def _write(self, bp_id: str, data: dict[str, Any]) -> None:
        path = self._dir / f"{bp_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            with open(path, encoding="utf-8") as f:
                result: dict[str, Any] = json.load(f)
                return result
        except (json.JSONDecodeError, OSError):
            return None
