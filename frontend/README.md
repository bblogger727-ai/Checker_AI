# CheckerAI Frontend

React + Vite frontend for CheckerAI, SetterAI, and MentorAI.

## Local Development

Start the three backends on their default ports:

- CheckerAI: `http://localhost:8000`
- SetterAI: `http://localhost:8001`
- MentorAI: `http://localhost:8002`

Then run:

```bash
npm install
npm run dev
```

The Vite dev server proxies API requests:

- `/api/*` -> CheckerAI
- `/api/setter/*` -> SetterAI
- `/api/mentor/*` -> MentorAI

## API Overrides

The frontend uses relative API URLs by default. To point at custom backend URLs, set:

```env
VITE_CHECKER_API_URL=http://localhost:8000
VITE_SETTER_API_URL=http://localhost:8001
VITE_MENTOR_API_URL=http://localhost:8002
```

## Production

In Docker, nginx serves the built React app and proxies the same API paths to the backend containers.
