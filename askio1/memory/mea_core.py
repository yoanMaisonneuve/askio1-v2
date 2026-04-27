"""
mea_core.py — Mémoire Externe Auto-construite (MEA) — Généré par Askio1 v2
"""

# CONTRAINTES IDENTIFIÉES
CONSTRAINTS = {
    'traceability': {
        'requirement': 'Audit trail complet des modifications',
        'implementation': 'Logging structuré + timestamps + hash de vérification',
        'criticality': 'HIGH'
    },
    'cognitive_robustness': {
        'requirement': 'Récupération gracieuse des erreurs d\'accès',
        'implementation': 'Try-catch + fallback + error logging',
        'criticality': 'HIGH'
    },
    'determinism': {
        'requirement': 'Reproductibilité du scoring pour audit',
        'implementation': 'Seed fixe + algorithme déterministe',
        'criticality': 'CRITICAL'
    },
    'external_memory': {
        'requirement': 'Sérialisation indépendante de la persistance',
        'implementation': 'Format JSON standardisé + versioning',
        'criticality': 'HIGH'
    }
}



from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
import hashlib
import json

@dataclass
class AccessLog:
    """Trace d'accès à une entrée mémoire"""
    timestamp: float
    access_type: str  # 'read', 'write', 'update', 'error'
    context: str
    success: bool
    error_msg: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)

@dataclass
class ImportanceMetadata:
    """Métadonnées d'importance multi-critères"""
    access_frequency: float = 0.0  # Nombre d'accès normalisé [0-1]
    recency_score: float = 0.0     # Basé sur temps écoulé [0-1]
    contextual_relevance: float = 0.0  # Pertinence au contexte [0-1]
    decision_impact: float = 0.0   # Impact sur décisions [0-1]
    user_priority: float = 0.5     # Priorité explicite [0-1]
    
    # Poids pour le scoring (variant testable)
    weights: Dict[str, float] = field(default_factory=lambda: {
        'access_frequency': 0.25,
        'recency_score': 0.30,
        'contextual_relevance': 0.25,
        'decision_impact': 0.15,
        'user_priority': 0.05
    })
    
    def compute_importance(self) -> float:
        """Scoring déterministe multi-critères"""
        score = (
            self.access_frequency * self.weights['access_frequency'] +
            self.recency_score * self.weights['recency_score'] +
            self.contextual_relevance * self.weights['contextual_relevance'] +
            self.decision_impact * self.weights['decision_impact'] +
            self.user_priority * self.weights['user_priority']
        )
        return min(1.0, max(0.0, score))  # Clamp [0-1]
    
    def to_dict(self) -> Dict:
        return asdict(self)

@dataclass
class MemoryEntry:
    """Entrée mémoire avec traçabilité complète"""
    id: str
    content: Any
    created_at: float
    updated_at: float
    
    # Métadonnées d'importance
    importance_metadata: ImportanceMetadata = field(default_factory=ImportanceMetadata)
    current_importance: float = 0.0
    
    # Traçabilité
    access_logs: List[AccessLog] = field(default_factory=list)
    modification_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    
    # Persistance
    is_external: bool = False  # Marque si en mémoire externe
    version: str = "1.0"
    system_id: str = "MEA_CORE"  # Identité du système
    
    # Decay temporel
    decay_factor: float = 1.0  # Multiplicateur d'importance (decay)
    decay_half_life: float = 86400.0  # 24h en secondes
    
    def compute_decay(self, current_time: float) -> float:
        """Decay exponentiel: importance *= exp(-ln(2) * t / half_life)"""
        time_elapsed = current_time - self.updated_at
        decay = 2.0 ** (-time_elapsed / self.decay_half_life)
        return max(0.0, min(1.0, decay))
    
    def update_importance(self, current_time: float) -> float:
        """Recalcule l'importance avec decay"""
        base_importance = self.importance_metadata.compute_importance()
        self.decay_factor = self.compute_decay(current_time)
        self.current_importance = base_importance * self.decay_factor
        return self.current_importance
    
    def log_access(self, access_type: str, context: str, 
                   success: bool = True, error_msg: Optional[str] = None):
        """Enregistre un accès avec traçabilité"""
        log = AccessLog(
            timestamp=datetime.now().timestamp(),
            access_type=access_type,
            context=context,
            success=success,
            error_msg=error_msg
        )
        self.access_logs.append(log)
        
        if not success:
            self.error_count += 1
            self.last_error = error_msg
    
    def compute_checksum(self) -> str:
        """Hash pour vérification d'intégrité"""
        content_str = json.dumps(self.content, default=str, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]
    
    def to_dict(self, include_logs: bool = True) -> Dict:
        """Sérialisation pour persistance externe"""
        data = {
            'id': self.id,
            'content': self.content,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'importance_metadata': self.importance_metadata.to_dict(),
            'current_importance': self.current_importance,
            'modification_count': self.modification_count,
            'error_count': self.error_count,
            'last_error': self.last_error,
            'is_external': self.is_external,
            'version': self.version,
            'system_id': self.system_id,
            'decay_factor': self.decay_factor,
            'checksum': self.compute_checksum()
        }
        if include_logs:
            data['access_logs'] = [log.to_dict() for log in self.access_logs]
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryEntry':
        """Désérialisation depuis persistance externe"""
        importance_data = data.pop('importance_metadata', {})
        access_logs_data = data.pop('access_logs', [])
        
        entry = cls(
            id=data['id'],
            content=data['content'],
            created_at=data['created_at'],
            updated_at=data['updated_at'],
            importance_metadata=ImportanceMetadata(**importance_data),
            current_importance=data.get('current_importance', 0.0),
            modification_count=data.get('modification_count', 0),
            error_count=data.get('error_count', 0),
            last_error=data.get('last_error'),
            is_external=data.get('is_external', False),
            version=data.get('version', '1.0'),
            system_id=data.get('system_id', 'MEA_CORE'),
            decay_factor=data.get('decay_factor', 1.0),
            decay_half_life=data.get('decay_half_life', 86400.0)
        )
        entry.access_logs = [AccessLog(**log) for log in access_logs_data]
        return entry



from typing import Callable
import math

class ImportanceScorer:
    """Moteur de scoring multi-critères avec variants testables"""
    
    def __init__(self, scoring_mode: str = 'weighted'):
        """
        scoring_mode: 'weighted' | 'learned' | 'contextual'
        """
        self.scoring_mode = scoring_mode
        self.access_history: Dict[str, List[float]] = {}
        self.learned_weights: Dict[str, float] = {}
    
    def update_access_frequency(self, entry: MemoryEntry, 
                                max_accesses: int = 100) -> float:
        """Normalise la fréquence d'accès [0-1]"""
        freq = len(entry.access_logs)
        normalized = min(1.0, freq / max_accesses)
        entry.importance_metadata.access_frequency = normalized
        return normalized
    
    def update_recency_score(self, entry: MemoryEntry, 
                            current_time: float,
                            decay_mode: str = 'exponential') -> float:
        """
        Calcule la récence avec différents modes de decay
        decay_mode: 'linear' | 'exponential' | 'hyperbolic'
        """
        time_elapsed = current_time - entry.updated_at
        
        if decay_mode == 'linear':
            # Decay linéaire: 1 - (t / max_age)
            max_age = 30 * 86400  # 30 jours
            score = max(0.0, 1.0 - (time_elapsed / max_age))
        
        elif decay_mode == 'exponential':
            # Decay exponentiel: exp(-t / tau)
            tau = 7 * 86400  # 7 jours
            score = math.exp(-time_elapsed / tau)
        
        elif decay_mode == 'hyperbolic':
            # Decay hyperbolique: 1 / (1 + t / tau)
            tau = 7 * 86400
            score = 1.0 / (1.0 + time_elapsed / tau)
        
        else:
            score = 0.0
        
        entry.importance_metadata.recency_score = min(1.0, max(0.0, score))
        return entry.importance_metadata.recency_score
    
    def update_contextual_relevance(self, entry: MemoryEntry, 
                                   context_keywords: List[str]) -> float:
        """Évalue la pertinence au contexte actuel"""
        if not context_keywords or not isinstance(entry.content, dict):
            entry.importance_metadata.contextual_relevance = 0.5
            return 0.5
        
        content_str = json.dumps(entry.content, default=str).lower()
        matches = sum(1 for kw in context_keywords if kw.lower() in content_str)
        
        relevance = min(1.0, matches / max(len(context_keywords), 1))
        entry.importance_metadata.contextual_relevance = relevance
        return relevance
    
    def update_decision_impact(self, entry: MemoryEntry, 
                              impact_score: float) -> float:
        """Marque l'impact sur les décisions du système"""
        entry.importance_metadata.decision_impact = min(1.0, max(0.0, impact_score))
        return impact_score
    
    def compute_importance(self, entry: MemoryEntry, 
                          current_time: float,
                          context_keywords: List[str] = None,
                          decay_mode: str = 'exponential') -> float:
        """Pipeline complet de scoring"""
        try:
            # Mise à jour des critères
            self.update_access_frequency(entry)
            self.update_recency_score(entry, current_time, decay_mode)
            if context_keywords:
                self.update_contextual_relevance(entry, context_keywords)
            
            # Calcul de l'importance
            importance = entry.importance_metadata.compute_importance()
            entry.update_importance(current_time)
            
            entry.log_access('score_update', 'importance_computation', success=True)
            return entry.current_importance
        
        except Exception as e:
            entry.log_access('score_update', 'importance_computation', 
                            success=False, error_msg=str(e))
            raise



class DecayManager:
    """Gestion du decay temporel avec variants"""
    
    @staticmethod
    def exponential_decay(time_elapsed: float, half_life: float) -> float:
        """Decay exponentiel: f(t) = 2^(-t/T)"""
        return 2.0 ** (-time_elapsed / half_life)
    
    @staticmethod
    def linear_decay(time_elapsed: float, max_age: float) -> float:
        """Decay linéaire: f(t) = max(0, 1 - t/T)"""
        return max(0.0, 1.0 - (time_elapsed / max_age))
    
    @staticmethod
    def hyperbolic_decay(time_elapsed: float, tau: float) -> float:
        """Decay hyperbolique: f(t) = 1/(1 + t/T)"""
        return 1.0 / (1.0 + time_elapsed / tau)
    
    @staticmethod
    def apply_decay_batch(entries: List[MemoryEntry], 
                         current_time: float,
                         decay_mode: str = 'exponential') -> Dict[str, float]:
        """Applique le decay à un batch d'entrées"""
        results = {}
        for entry in entries:
            time_elapsed = current_time - entry.updated_at
            
            if decay_mode == 'exponential':
                decay = DecayManager.exponential_decay(time_elapsed, entry.decay_half_life)
            elif decay_mode == 'linear':
                decay = DecayManager.linear_decay(time_elapsed, 30 * 86400)
            elif decay_mode == 'hyperbolic':
                decay = DecayManager.hyperbolic_decay(time_elapsed, entry.decay_half_life)
            else:
                decay = 1.0
            
            entry.decay_factor = decay
            entry.current_importance *= decay
            results[entry.id] = entry.current_importance
        
        return results
