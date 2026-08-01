from pathlib import Path
import os
import glob

class ProjectContext:
    """
    Manages project-specific paths and context.
    All outputs for a project are stored in output/{project_name}/...
    On HuggingFace the working directory is /app, so paths resolve to
    /app/output/{project_name}/... On local dev, they resolve to output/...
    """
    
    def __init__(self, project_name: str = "default"):
        self.name = project_name
        # Use absolute /app/output on HuggingFace, relative output/ locally.
        # This fixes Step 6's _extract_from_page_text and _scan_all_pages
        # which use context.get_path() to find step1_extraction/accepted/page_N.txt
        if Path("/app").exists():
            self.base_path = Path("/app/output") / project_name
        else:
            self.base_path = Path("output") / project_name
        
        # Ensure base project folder exists
        self.base_path.mkdir(parents=True, exist_ok=True)
        
    def get_path(self, *parts) -> Path:
        """Get a path within the project folder."""
        path = self.base_path.joinpath(*parts)
        if "." not in path.name: # Assume it's a directory if no extension
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path
        
    @staticmethod
    def list_projects() -> list:
        """
        Legacy CLI path — kept for local non-web usage.
        List all existing project names.
        """
        if not os.path.exists("output"):
            return []
        
        # Only counting directories that look like projects (not files like total_costs.json)
        projects = []
        for d in os.listdir("output"):
            path = os.path.join("output", d)
            if os.path.isdir(path) and d != "global":
                projects.append(d)
        return sorted(projects)
