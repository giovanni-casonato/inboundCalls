import time
import json
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class LatencyMeasurement:
    stage: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    metadata: Optional[Dict] = None

class LatencyTracker:
    """
    Comprehensive latency tracking system for voice pipeline
    """
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.measurements: List[LatencyMeasurement] = []
        self.active_measurements: Dict[str, LatencyMeasurement] = {}
        self.conversation_start = time.time()
        
    def start_measurement(self, stage: str, metadata: Dict = None) -> str:
        """Start timing a specific stage"""
        measurement_id = f"{stage}_{int(time.time() * 1000)}"
        measurement = LatencyMeasurement(
            stage=stage,
            start_time=time.time(),
            metadata=metadata or {}
        )
        self.active_measurements[measurement_id] = measurement
        return measurement_id
        
    def end_measurement(self, measurement_id: str, metadata: Dict = None) -> Optional[float]:
        """End timing and calculate duration"""
        if measurement_id not in self.active_measurements:
            print(f"⚠️ Warning: No active measurement found for {measurement_id}")
            return None
            
        measurement = self.active_measurements.pop(measurement_id)
        measurement.end_time = time.time()
        measurement.duration_ms = (measurement.end_time - measurement.start_time) * 1000
        
        if metadata:
            measurement.metadata.update(metadata)
            
        self.measurements.append(measurement)
        
        # Log immediately for real-time monitoring
        self._log_measurement(measurement)
        
        return measurement.duration_ms
        
    def _log_measurement(self, measurement: LatencyMeasurement):
        """Log measurement with color coding for quick identification"""
        duration = measurement.duration_ms
        
        # Color coding based on duration
        if duration < 100:
            color = "🟢"  # Green - Good
        elif duration < 500:
            color = "🟡"  # Yellow - Acceptable
        elif duration < 1000:
            color = "🟠"  # Orange - Concerning
        else:
            color = "🔴"  # Red - Poor
            
        print(f"{color} {measurement.stage}: {duration:.1f}ms {measurement.metadata}")
        
    def get_pipeline_summary(self) -> Dict:
        """Get summary of all measurements in the current pipeline"""
        if not self.measurements:
            return {"error": "No measurements recorded"}
            
        # Group by stage
        by_stage = {}
        for m in self.measurements:
            if m.stage not in by_stage:
                by_stage[m.stage] = []
            by_stage[m.stage].append(m.duration_ms)
            
        # Calculate averages
        summary = {}
        total_avg = 0
        for stage, durations in by_stage.items():
            avg = sum(durations) / len(durations)
            summary[stage] = {
                "avg_ms": round(avg, 1),
                "min_ms": round(min(durations), 1),
                "max_ms": round(max(durations), 1),
                "count": len(durations)
            }
            total_avg += avg
            
        summary["total_pipeline_avg"] = round(total_avg, 1)
        summary["session_duration"] = round((time.time() - self.conversation_start), 1)
        
        return summary
        
    def log_summary(self):
        """Print a detailed summary"""
        summary = self.get_pipeline_summary()
        print("\n" + "="*60)
        print(f"📊 LATENCY SUMMARY - Session: {self.session_id}")
        print("="*60)
        
        if "error" in summary:
            print(summary["error"])
            return
            
        for stage, stats in summary.items():
            if stage in ["total_pipeline_avg", "session_duration"]:
                continue
                
            avg = stats["avg_ms"]
            color = "🟢" if avg < 200 else "🟡" if avg < 500 else "🟠" if avg < 1000 else "🔴"
            print(f"{color} {stage:25} Avg: {avg:6.1f}ms  Min: {stats['min_ms']:6.1f}ms  Max: {stats['max_ms']:6.1f}ms  Count: {stats['count']}")
            
        print("-" * 60)
        print(f"🎯 Total Pipeline Average: {summary['total_pipeline_avg']:.1f}ms")
        print(f"⏱️  Session Duration: {summary['session_duration']:.1f}s")
        print("="*60)
