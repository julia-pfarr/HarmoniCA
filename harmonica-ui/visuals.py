import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Palette from the HarmoniCA logo: the colours of its pills, ordered so neighbouring series differ clearly
COLORS=['#2A6DB5','#E8834E','#4AA8A0','#F5B041','#174A80','#7AAB5A','#C45A24','#2A9DB0','#146B66','#C4BD55','#4A8433','#D48C12']
INK='#16303D'

def decorate(fig):
    fig.update_layout(template='plotly_white',font=dict(family='Inter, Arial, sans-serif',color=INK),paper_bgcolor='rgba(0,0,0,0)',margin=dict(l=20,r=20,t=35,b=25),colorway=COLORS)
    return fig

def flow_figure(df):
    instruments=list(df.questionnaire.unique())
    dimensions=list(df.dimension_label.unique())
    grouped=df.groupby(['questionnaire','dimension_label']).size().reset_index(name='n')
    return decorate(go.Figure(go.Sankey(node=dict(label=instruments+dimensions,pad=24,thickness=18,color=[COLORS[i%len(COLORS)] for i in range(len(instruments)+len(dimensions))]),link=dict(source=[instruments.index(q) for q in grouped.questionnaire],target=[len(instruments)+dimensions.index(d) for d in grouped.dimension_label],value=grouped.n,color='rgba(15,76,107,.18)'))))

def confidence_figure(df):
    frame=df.copy();frame['confidence']=pd.to_numeric(frame.confidence,errors='coerce')
    return decorate(px.histogram(frame,x='confidence',color='questionnaire',color_discrete_sequence=COLORS,nbins=20,barmode='overlay',opacity=.65,range_x=[0,1],labels={'confidence':'Engine assignment confidence'}))
