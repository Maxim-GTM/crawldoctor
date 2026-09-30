# 🕷️ CrawlDoctor - AI Crawler Tracking System

A comprehensive system for tracking and analyzing AI crawler visits to your website. CrawlDoctor specializes in detecting visits from AI crawlers like ChatGPT, Claude, Perplexity, and Google AI Studio that traditional analytics miss.

## 🌟 Features

### Core Tracking
- **🤖 AI Crawler Detection**: Advanced detection of AI crawlers using user agent patterns and behavioral analysis
- **📊 Real-time Analytics**: Live tracking dashboard with real-time updates
- **🌍 Geographic Tracking**: IP-based location detection with country/city mapping
- **📱 Multiple Tracking Methods**: Pixel tracking, beacon API, and resource-based tracking

### Advanced Analytics
- **📈 Time Series Analysis**: Track crawler activity over time with detailed charts
- **🔍 Crawler Comparison**: Compare different AI crawlers side-by-side
- **📋 Detailed Reports**: Export data in CSV/JSON formats
- **⚡ Real-time Dashboard**: Live monitoring with auto-refresh capabilities

### Security & Performance
- **🔒 Single Sign-On**: Dashboard sign-in through the GTM Hub, with role-based permissions
- **⚡ Rate Limiting**: Redis-based rate limiting to prevent abuse
- **🛡️ Input Validation**: Comprehensive validation and sanitization
- **🚀 High Performance**: Async FastAPI backend with optimized database queries

### Deployment Ready
- **🐳 Docker Support**: Complete containerization with multi-stage builds
- **☁️ Fly.io Ready**: Pre-configured for Fly.io deployment
- **📊 Health Checks**: Built-in health monitoring and metrics
- **🔧 Environment Management**: Comprehensive configuration system

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Website with  │    │   Blog/Static   │    │   Any Web Page  │
│   Tracking Code │    │   Site + Pixel  │    │   + SDK/Beacon  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   FastAPI       │
                    │   Tracking API  │
                    │   + Dashboard   │
                    └─────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   PostgreSQL    │    │     Redis       │    │   React         │
│   (Analytics    │    │   (Rate Limit   │    │   Dashboard     │
│    Storage)     │    │    & Cache)     │    │   (Protected)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd GEO-CrawlDoctor
   ```

2. **Start the services**:
   ```bash
   docker-compose up -d
   ```

3. **Access the dashboard**:
   - Open http://localhost:8000
   - Sign-in goes through the GTM Hub (see [Sign-in](#sign-in-gtm-hub-single-sign-on)); for local
     development set `HUB_SSO_DISABLED=true` to skip it

### Option 2: Fly.io Deployment

1. **Install Fly CLI**:
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```

2. **Deploy to Fly.io**:
   ```bash
   fly launch
   fly deploy
   ```

3. **Set up database**:
   ```bash
   fly postgres create
   fly secrets set CRAWLDOCTOR_DATABASE_URL="your-postgres-url"
   ```

### Option 3: Local Development

1. **Install dependencies**:
   ```bash
   # Backend
   pip3 install -r requirements.txt
   
   # Frontend
   cd frontend && npm install
   ```

2. **Set up environment**:
   ```bash
   cp env.example .env
   # Edit .env with your configuration; for local development add HUB_SSO_DISABLED=true
   ```
   Leave `REACT_APP_API_URL` unset so `npm start` proxies `/api` to the backend on the same origin
   (the hub sign-in exchange refuses cross-origin requests).

3. **Start services**:
   ```bash
   # Backend
   uvicorn app.main:app --reload
   
   # Frontend (in another terminal)
   cd frontend && npm start
   ```

## 📊 Adding Tracking to Your Website

### JavaScript Tracker (Required)
```html
<!-- JS-only tracking with full event capture -->
<script src="https://your-domain.com/track/js?tid=your-tracking-id"></script>
```

## 🤖 Detected AI Crawlers

CrawlDoctor automatically detects and classifies these AI crawlers:

- **🧠 OpenAI**: ChatGPT, GPTBot, OpenAI crawlers
- **🎭 Anthropic**: Claude, ClaudeBot, Anthropic crawlers  
- **🔍 Perplexity**: PerplexityBot, pplx-ai crawlers
- **🏢 Google AI**: Bard, Gemini, Google-Extended
- **🚀 Microsoft**: Copilot, EdgeGPT, Bing AI
- **📱 Meta AI**: Meta-ExternalAgent, FacebookBot-AI
- **🤗 Hugging Face**: Various ML model crawlers
- **🔬 Research Bots**: Academic and research crawlers

## 🔧 Configuration

### Environment Variables

Key configuration options (see `env.example` for complete list):

```bash
# Database
CRAWLDOCTOR_DATABASE_URL="postgresql://user:pass@host:5432/db"

# Security
CRAWLDOCTOR_SECRET_KEY="your-secret-key"
CRAWLDOCTOR_ADMIN_PASSWORD="secure-password"

# Rate Limiting
CRAWLDOCTOR_RATE_LIMIT_REQUESTS=1000
CRAWLDOCTOR_RATE_LIMIT_WINDOW=60

# CORS
CRAWLDOCTOR_CORS_ORIGINS='["https://yourdomain.com"]'
```

### Sign-in (GTM Hub single sign-on)

People sign in to the dashboard through the GTM Hub (https://hub.agitracker.io); CrawlDoctor has no
login page of its own. On every page load the dashboard calls `GET /api/v1/auth/hub`, which asks the
hub (`{HUB_URL}/api/sso/verify?app=crawldoctor`, forwarding only the `better-auth.` cookies) whether
this browser may use CrawlDoctor:

- **Allowed**: the local user is found or created by email (hub admins are CrawlDoctor admins; the role
  is re-synced on every sign-in) and the usual access token is returned.
- **Not signed in**: the browser goes to the hub login page and comes back afterwards.
- **No access**: the browser goes to the hub's no-access page.
- **Hub unreachable**: the dashboard shows "Sign-in service unavailable" (it fails closed).

Every `*.agitracker.io` site receives the hub cookie, so the exchange refuses browser requests whose
`Sec-Fetch-Site` is `same-site` or `cross-site`: only CrawlDoctor's own pages can get a token.
"Sign out" goes to the hub's sign-out page. It and the signed-in user at the foot of the sidebar show
only when CrawlDoctor is opened on its own; inside the hub, the hub's sidebar has them.

| Variable | Default | Purpose |
| --- | --- | --- |
| `HUB_URL` | `https://hub.agitracker.io` | GTM Hub base URL |
| `APP_PUBLIC_URL` | `https://crawldoctor.agitracker.io` | Where the hub sends people back after sign-in |
| `HUB_APP_SLUG` | `crawldoctor` | This app's slug in the hub |
| `HUB_SSO_DISABLED` | `false` | Local development only: skip the hub; everyone is `dev@localhost` (admin) |
| `CRAWLDOCTOR_ALLOW_PASSWORD_LOGIN` | `false` | Break-glass: re-enable `POST /api/v1/auth/login` and `PUT /api/v1/auth/password` |

The first four have no `CRAWLDOCTOR_` prefix. No variables were removed: `CRAWLDOCTOR_ADMIN_*` still
bootstrap the local `admin` account, which can only sign in while `CRAWLDOCTOR_ALLOW_PASSWORD_LOGIN=true`
(set a strong `CRAWLDOCTOR_ADMIN_PASSWORD` before turning it on). Unchanged: the public `/track/*`
endpoints and their CORS, `/health`, `/test/*`, export API keys (`X-Export-API-Key`) and per-user API
keys (`X-API-Key`).

### Custom Crawler Patterns

Add custom crawler detection patterns via the admin panel:

```python
# Example: Custom crawler pattern
{
    "crawler_name": "Custom-AI-Bot",
    "pattern": r"CustomBot\/\d+\.\d+",
    "description": "Custom AI crawler",
    "confidence_score": 0.9
}
```

## 📈 API Usage

### Authentication
```bash
# Use your API key
curl -H "X-API-Key: your-api-key" \
     "https://your-domain.com/api/v1/analytics/summary"

# Break-glass only (CRAWLDOCTOR_ALLOW_PASSWORD_LOGIN=true): get an access token with a password
curl -X POST "https://your-domain.com/api/v1/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "your-admin-password"}'
```

### Analytics API
```bash
# Get summary statistics
curl -H "Authorization: Bearer TOKEN" \
     "https://your-domain.com/api/v1/analytics/summary"

# Get real-time data
curl -H "Authorization: Bearer TOKEN" \
     "https://your-domain.com/api/v1/analytics/realtime"

# Export data
curl -H "Authorization: Bearer TOKEN" \
     "https://your-domain.com/api/v1/analytics/export?format=csv"
```

## 🛠️ Development

### Project Structure
```
GEO-CrawlDoctor/
├── app/                    # FastAPI backend
│   ├── api/               # API routes
│   ├── models/            # Database models
│   ├── services/          # Business logic
│   └── utils/             # Utilities
├── frontend/              # React dashboard
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── pages/         # Page components
│   │   └── utils/         # Frontend utilities
├── docker-compose.yml     # Local development
├── Dockerfile            # Production container
└── fly.toml              # Fly.io configuration
```

### Running Tests
```bash
# Backend tests
python3 -m pytest

# Frontend tests
cd frontend && npm test
```

### Database Migrations
```bash
# Create migration
alembic revision --autogenerate -m "description"

# Run migrations
alembic upgrade head
```

## 🔐 Security Considerations

### Data Privacy
- Only tracks AI crawlers, not human visitors
- IP addresses can be anonymized for GDPR compliance
- No personal data collection from crawlers
- Configurable data retention policies

### Production Security
- Change default admin credentials
- Use strong secret keys
- Enable HTTPS/TLS
- Configure CORS properly
- Set up rate limiting
- Regular security updates

## 📊 Monitoring & Maintenance

### Health Checks
- `/health` - Application health
- `/metrics` - Prometheus metrics
- Database connection monitoring
- Redis connectivity checks

### Maintenance Tasks
```bash
# Cleanup old data
curl -X POST -H "Authorization: Bearer TOKEN" \
     "https://your-domain.com/api/v1/admin/cleanup?retention_days=365"

# View system stats
curl -H "Authorization: Bearer TOKEN" \
     "https://your-domain.com/api/v1/admin/stats"
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

- **Documentation**: Check the `/embed` page in your dashboard
- **API Docs**: Visit `/docs` (in debug mode)
- **Health Status**: Monitor `/health` endpoint
- **Issues**: Report bugs via GitHub issues

## 🔮 Roadmap

- [ ] **Enhanced Geographic Analytics**: Detailed country/city reports
- [ ] **Alert System**: Email/Slack notifications for unusual activity
- [ ] **Advanced Filtering**: Custom date ranges and complex filters
- [ ] **Webhook Support**: Real-time event notifications
- [ ] **Multi-tenant Support**: Multiple websites per instance
- [ ] **Machine Learning**: Behavioral analysis for better detection
- [ ] **Mobile App**: iOS/Android dashboard apps

---

**Built with ❤️ for monitoring AI crawler activity**

Track what traditional analytics miss with CrawlDoctor's specialized AI crawler detection system.
