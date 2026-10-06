import ast
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Palette from the HarmoniCA Figma template: brand red first, then muted complements
COLORS=['#A33B5C','#2F6B57','#D08A3C','#5B6C9A','#CF7090','#7A8B99']
SEQUENTIAL=[[0,'#FBF3F5'],[0.5,'#E3A3B7'],[1,'#A33B5C']]

def decorate(fig):
    fig.update_layout(template='plotly_white',font=dict(family='Inter, Arial, sans-serif',color='#1F2430'),paper_bgcolor='rgba(0,0,0,0)',margin=dict(l=20,r=20,t=35,b=25),colorway=COLORS)
    return fig

def flow_figure(df):
    instruments=list(df.questionnaire.unique())
    dimensions=list(df.dimension_label.unique())
    grouped=df.groupby(['questionnaire','dimension_label']).size().reset_index(name='n')
    return decorate(go.Figure(go.Sankey(node=dict(label=instruments+dimensions,pad=24,thickness=18,color=[COLORS[i%len(COLORS)] for i in range(len(instruments)+len(dimensions))]),link=dict(source=[instruments.index(q) for q in grouped.questionnaire],target=[len(instruments)+dimensions.index(d) for d in grouped.dimension_label],value=grouped.n,color='rgba(163,59,92,.18)'))))

def coverage_figure(df,normalize=False):
    counts=pd.crosstab(df.questionnaire,df.dimension_label)
    values=counts.div(counts.sum(axis=1),axis=0)*100 if normalize else counts
    return decorate(px.imshow(values,text_auto='.1f' if normalize else True,aspect='auto',color_continuous_scale=SEQUENTIAL,labels=dict(x='Dimension',y='Questionnaire',color='% of items' if normalize else 'Items')))

def confidence_figure(df):
    frame=df.copy();frame['confidence']=pd.to_numeric(frame.confidence,errors='coerce')
    return decorate(px.histogram(frame,x='confidence',color='questionnaire',nbins=20,barmode='overlay',opacity=.65,range_x=[0,1],labels={'confidence':'Engine assignment confidence'}))

def probabilities(value):
    if not value or str(value)=='nan': return {}
    try: data=json.loads(value)
    except (ValueError,TypeError):
        try:data=ast.literal_eval(value)
        except (ValueError,SyntaxError):return {}
    if not isinstance(data,dict):return {}
    try:return {str(k):float(v) for k,v in data.items()}
    except (ValueError,TypeError):return {}
