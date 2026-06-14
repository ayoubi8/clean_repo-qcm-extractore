from typing import List

class PromptHelper:
    """Collect and manage user guidance prompts"""
    
    @staticmethod
    def get_user_guidance(step_name: str, context: str = "", examples: List[str] = None) -> str:
        """
        Collect guidance from user
        
        Args:
            step_name: e.g., "OCR Page 2", "Metadata Detection"
            context: Additional info
            examples: List of example prompts
        """
        print(f"\n{'─'*50}")
        print(f"📝 {step_name}")
        print(f"{'─'*50}")
        
        if context:
            print(f"Context: {context}")
        
        if examples:
            print("\nExamples:")
            for ex in examples:
                print(f"  • {ex}")
        
        print("\nEnter your guidance (or press Enter to skip):")
        guidance = input("Your guidance: ").strip()
        return guidance
    
    @staticmethod
    def confirm_action(prompt: str, default: str = "y") -> bool:
        """Ask yes/no confirmation"""
        choice = input(f"{prompt} [Y/n]: ").strip().lower() or default
        return choice == "y"
