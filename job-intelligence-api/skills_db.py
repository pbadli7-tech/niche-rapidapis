"""
Curated skills database for extracting in-demand skills from job descriptions.
Organized by category for structured output.
"""

SKILLS_DB = {
    "programming_languages": [
        "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Rust",
        "Ruby", "PHP", "Swift", "Kotlin", "Scala", "R", "MATLAB", "Perl",
        "Dart", "Elixir", "Haskell", "Lua", "Julia", "Groovy", "Objective-C",
        "Assembly", "COBOL", "Fortran", "VBA", "Bash", "PowerShell", "Shell",
    ],
    "web_frameworks": [
        "React", "Angular", "Vue", "Next.js", "Nuxt", "Svelte", "Django",
        "FastAPI", "Flask", "Spring Boot", "Spring", "Express", "Node.js",
        "NestJS", "Laravel", "Rails", "Ruby on Rails", "ASP.NET", ".NET",
        "Gin", "Echo", "Fiber", "Actix", "Rocket", "Phoenix", "Remix",
        "Gatsby", "Astro", "SvelteKit", "Solid", "Qwik",
    ],
    "mobile": [
        "React Native", "Flutter", "iOS", "Android", "SwiftUI", "Jetpack Compose",
        "Xamarin", "Ionic", "Capacitor", "Expo", "Cordova",
    ],
    "databases": [
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "Cassandra",
        "DynamoDB", "Elasticsearch", "Neo4j", "CouchDB", "Firebase",
        "Firestore", "Supabase", "PlanetScale", "CockroachDB", "ClickHouse",
        "Snowflake", "BigQuery", "Redshift", "Oracle", "SQL Server", "MariaDB",
        "TimescaleDB", "InfluxDB", "Pinecone", "Weaviate", "Chroma",
    ],
    "cloud_devops": [
        "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform", "Ansible",
        "Jenkins", "GitHub Actions", "GitLab CI", "CircleCI", "ArgoCD",
        "Helm", "Istio", "Prometheus", "Grafana", "Datadog", "New Relic",
        "CloudFormation", "Pulumi", "Vagrant", "Nginx", "Apache", "Caddy",
        "Lambda", "ECS", "EKS", "GKE", "AKS", "Fargate", "EC2", "S3",
        "RDS", "Cloud Run", "App Engine", "Vercel", "Netlify", "Heroku",
        "Railway", "Fly.io", "DigitalOcean", "Linode",
    ],
    "ai_ml": [
        "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
        "TensorFlow", "PyTorch", "Keras", "scikit-learn", "Hugging Face",
        "LangChain", "OpenAI", "GPT", "LLM", "RAG", "Fine-tuning",
        "XGBoost", "LightGBM", "CatBoost", "Pandas", "NumPy", "SciPy",
        "Matplotlib", "Seaborn", "Plotly", "Jupyter", "MLflow", "Weights & Biases",
        "Vertex AI", "SageMaker", "Azure ML", "ONNX", "TensorRT",
        "Stable Diffusion", "Diffusion Models", "Transformers",
        "BERT", "GPT-4", "Claude", "Llama", "Mistral", "Gemini",
    ],
    "data_engineering": [
        "Apache Spark", "Apache Kafka", "Apache Airflow", "dbt", "Flink",
        "Hadoop", "Hive", "Presto", "Trino", "Databricks", "Delta Lake",
        "Apache Beam", "Dagster", "Prefect", "Luigi", "ETL", "ELT",
        "Data Pipeline", "Data Lake", "Data Warehouse", "Data Lakehouse",
        "Streaming", "Batch Processing", "Real-time Analytics",
    ],
    "tools_platforms": [
        "Git", "GitHub", "GitLab", "Bitbucket", "Jira", "Confluence",
        "Slack", "Notion", "Figma", "Postman", "Swagger", "OpenAPI",
        "Linux", "Unix", "Windows Server", "macOS", "REST API", "GraphQL",
        "gRPC", "WebSocket", "OAuth", "JWT", "SAML", "LDAP",
        "Microservices", "Serverless", "Event-Driven", "CQRS",
        "Agile", "Scrum", "Kanban", "DevOps", "CI/CD", "TDD", "BDD",
    ],
    "business_skills": [
        "Project Management", "Product Management", "Data Analysis",
        "Business Intelligence", "Power BI", "Tableau", "Looker",
        "Excel", "SQL", "Google Analytics", "SEO", "Digital Marketing",
        "Communication", "Leadership", "Team Management", "Stakeholder Management",
        "Problem Solving", "Critical Thinking", "Analytical Skills",
        "Requirements Gathering", "Technical Writing", "Presentation",
    ],
    "security": [
        "Cybersecurity", "Penetration Testing", "OWASP", "SOC", "SIEM",
        "Splunk", "IAM", "Zero Trust", "Encryption", "PKI", "SSL/TLS",
        "Vulnerability Assessment", "Threat Modeling", "Security Audit",
        "Compliance", "GDPR", "HIPAA", "ISO 27001", "SOC 2",
    ],
}

# Flat list for fast lookup (lowercase → canonical)
_SKILL_LOOKUP: dict[str, str] = {}
for _cat, _skills in SKILLS_DB.items():
    for _s in _skills:
        _SKILL_LOOKUP[_s.lower()] = _s

# Also add common aliases
_ALIASES = {
    "node": "Node.js",
    "nodejs": "Node.js",
    "react.js": "React",
    "reactjs": "React",
    "vue.js": "Vue",
    "vuejs": "Vue",
    "angular.js": "Angular",
    "angularjs": "Angular",
    "next": "Next.js",
    "postgres": "PostgreSQL",
    "mongo": "MongoDB",
    "k8s": "Kubernetes",
    "tf": "TensorFlow",
    "pytorch": "PyTorch",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "gpt-4": "GPT-4",
    "chatgpt": "GPT",
    "openai api": "OpenAI",
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "nlp": "NLP",
    "cv": "Computer Vision",
    "aws lambda": "Lambda",
    "amazon web services": "AWS",
    "google cloud": "GCP",
    "microsoft azure": "Azure",
    "spring framework": "Spring",
    "ruby on rails": "Rails",
    "asp.net core": "ASP.NET",
    "dotnet": ".NET",
    "dot net": ".NET",
}
for _alias, _canonical in _ALIASES.items():
    _SKILL_LOOKUP[_alias.lower()] = _canonical


def get_category(skill: str) -> str:
    """Return the category name for a given canonical skill name."""
    for cat, skills in SKILLS_DB.items():
        if skill in skills:
            return cat
    return "other"


def extract_skills(text: str) -> list[str]:
    """
    Extract skills mentioned in text using keyword matching.
    Returns list of canonical skill names (deduped, ordered by position of first mention).
    """
    if not text:
        return []

    text_lower = text.lower()
    found: dict[str, int] = {}  # skill -> first position

    # Sort by length (longest first) to match "Next.js" before "Next"
    for term_lower, canonical in sorted(_SKILL_LOOKUP.items(), key=lambda x: -len(x[0])):
        pos = text_lower.find(term_lower)
        if pos != -1:
            # Ensure it's a word boundary (not part of a larger word)
            before = text_lower[pos - 1] if pos > 0 else " "
            after = text_lower[pos + len(term_lower)] if pos + len(term_lower) < len(text_lower) else " "
            if before in " \n\t,;:()/\\\"'•-–—[]|+" and after in " \n\t,;:()/\\\"'•-–—[]|+":
                if canonical not in found:
                    found[canonical] = pos

    # Sort by first occurrence position
    return [skill for skill, _ in sorted(found.items(), key=lambda x: x[1])]
