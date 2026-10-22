"""Prove CUDA execution and causal temporal convolutions, without training on test data."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
    import torch
    from train_station_tcn import TemporalCNN
except ImportError:torch=None


@unittest.skipUnless(torch is not None and torch.cuda.is_available(),'CUDA PyTorch environment is required')
class CudaTCNChecks(unittest.TestCase):
    def test_causal_hidden_states_and_real_cuda_gradient(self):
        torch.manual_seed(42);model=TemporalCNN(29,channels=16).cuda().eval()
        x=torch.randn(2,29,72,device='cuda');future=x.clone();future[:,:,60:]+=100
        with torch.no_grad():
            old=model.blocks(x);new=model.blocks(future)
        self.assertTrue(old.is_cuda)
        self.assertTrue(torch.allclose(old[:,:,:60],new[:,:,:60],atol=1e-5,rtol=1e-5))
        prediction=model(x);self.assertEqual(tuple(prediction.shape),(2,6))
        (prediction-1).square().sum().backward()
        self.assertTrue(model.head.weight.grad.is_cuda)
        self.assertGreater(model.head.weight.grad.abs().sum().item(),0)


if __name__=='__main__':unittest.main()
