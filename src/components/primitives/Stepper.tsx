import { Step, StepLabel, Stepper as MuiStepper } from '@mui/material';

export function Stepper({ steps, activeStep = 0 }: { steps: string[]; activeStep?: number }) {
  return <MuiStepper activeStep={activeStep}>{steps.map((step) => <Step key={step}><StepLabel>{step}</StepLabel></Step>)}</MuiStepper>;
}
